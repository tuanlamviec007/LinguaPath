"""Read-only retrieval fixtures and guarded, aggregate-only report writes."""
from contextlib import ExitStack
from io import StringIO
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from .models import Flashcard, LearningContent
from .management.commands.evaluate_retrieval import FIXED_BENCHMARKS, ROOT, MAX_FIXTURE_BYTES


class RetrievalCommandSafetyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.content = LearningContent.objects.create(title='Retrieval safety', exam_type='TOEIC',
            content_type='vocabulary', skill='vocabulary', is_published=True, review_status='language_checked')
        cls.bank = Flashcard.objects.create(content=cls.content, term='bank', meaning_vi='ngân hàng')
        cls.charge = Flashcard.objects.create(content=cls.content, term='charge', meaning_vi='khoản phí')

    def fixture(self, directory, cases=None):
        path = Path(directory) / 'fixture.json'
        data = {'version':'safety-regression', 'cases': cases if cases is not None else [
            {'id':'sense', 'split':'dev', 'category':'sense', 'query':'What does bank mean?', 'expected_terms':['bank'],
             'expected_senses':[{'term':'bank','meaning_vi':'ngân hàng'}], 'ambiguity_required':True}]}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return path

    def mocks(self, stack, retrieved=None):
        retrieved = retrieved if retrieved is not None else [{'term':'bank','meaning_vi':'bờ sông','ambiguous':True}]
        return [stack.enter_context(patch(name, return_value=retrieved)) for name in (
            'learning.management.commands.evaluate_retrieval.baseline_retrieve',
            'learning.management.commands.evaluate_retrieval.previous_retrieve',
            'learning.retrieval.retrieve_context')]

    def assert_preflight_rejected(self, source, output=None, **options):
        with ExitStack() as stack:
            retrievers = self.mocks(stack)
            with self.assertRaises(CommandError):
                call_command('evaluate_retrieval', benchmark_file=source, output=output, stdout=StringIO(), **options)
            for retriever in retrievers:
                retriever.assert_not_called()

    def test_custom_fixture_reports_separate_sense_denominators_and_provenance(self):
        with TemporaryDirectory() as directory, ExitStack() as stack:
            source = self.fixture(directory)
            target = Path(directory)/'report.json'
            retrievers = self.mocks(stack)
            out = StringIO()
            call_command('evaluate_retrieval', benchmark_file=source, output=target, stdout=out)
            report = json.loads(target.read_text())
            metrics = report['improved']['overall']
            self.assertEqual(metrics['recall_at_3'],1)
            self.assertEqual(metrics['sense_labeled_queries'],1)
            self.assertEqual(metrics['sense_recall_at_3'],0)
            self.assertEqual(metrics['ambiguity_labeled_queries'],1)
            self.assertEqual(metrics['ambiguity_accuracy'],1)
            self.assertEqual(report['benchmark_sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(report['scorer_sha256'],hashlib.sha256((ROOT/'learning/retrieval_evaluation.py').read_bytes()).hexdigest())
            self.assertTrue(report['sense_match_policy']['preserves_accents'])
            self.assertFalse(report['sense_match_policy']['semantic_equivalence'])
            self.assertIn('not independent holdout',report['scope'])
            self.assertIn('not independent holdout',out.getvalue())
            self.assertNotIn('What does bank mean?',target.read_text())
            self.assertNotIn('ngân hàng',target.read_text())
            for retriever in retrievers: retriever.assert_called_once_with('What does bank mean?',limit=3)

    def test_invalid_sense_pair_fails_before_retrieval(self):
        with TemporaryDirectory() as directory:
            source=self.fixture(directory)
            value=json.loads(source.read_text());value['cases'][0]['expected_senses'][0]['meaning_vi']='Nghĩa chưa có'
            source.write_text(json.dumps(value))
            self.assert_preflight_rejected(source)

    def test_held_and_foreign_exam_cards_do_not_satisfy_sense_gold(self):
        with TemporaryDirectory() as directory:
            source=self.fixture(directory)
            self.bank.is_available=False;self.bank.save(update_fields=['is_available'])
            foreign=LearningContent.objects.create(title='Foreign',exam_type='IELTS',content_type='vocabulary',is_published=True,review_status='language_checked')
            Flashcard.objects.create(content=foreign,term='bank',meaning_vi='ngân hàng')
            self.assert_preflight_rejected(source)

    def test_dev_default_does_not_look_up_unseen_test_headword_or_emit_query(self):
        cases=[{'id':'dev','split':'dev','category':'word','query':'development query','expected_terms':['bank']},
               {'id':'test','split':'test','category':'sense','query':'unseen test query','expected_terms':['unseen-test-target'],
                'expected_senses':[{'term':'unseen-test-target','meaning_vi':'unseen test sense'}]}]
        with TemporaryDirectory() as directory, ExitStack() as stack:
            source=self.fixture(directory,cases);target=Path(directory)/'report.json'
            retrievers=self.mocks(stack)
            output=StringIO()
            call_command('evaluate_retrieval',benchmark_file=source,output=target,stdout=output)
            report=json.loads(target.read_text())
            self.assertEqual(set(report['improved']['by_split']),{'dev'})
            self.assertEqual(report['improved']['overall']['sense_labeled_queries'],0)
            self.assertNotIn('unseen test query',target.read_text()+output.getvalue())
            for retriever in retrievers: retriever.assert_called_once_with('development query',limit=3)
            self.assert_preflight_rejected(source,include_test=True)

    def test_dev_does_not_look_up_missing_test_sense_of_existing_other_headword(self):
        cases=[{'id':'dev','split':'dev','category':'word','query':'bank','expected_terms':['bank']},
               {'id':'test','split':'test','category':'sense','query':'charge','expected_terms':['charge'],
                'expected_senses':[{'term':'charge','meaning_vi':'missing test-only sense'}]}]
        with TemporaryDirectory() as directory, ExitStack() as stack:
            source=self.fixture(directory,cases);self.mocks(stack)
            call_command('evaluate_retrieval',benchmark_file=source,stdout=StringIO())
            self.assert_preflight_rejected(source,include_test=True)

    def test_output_input_hardlink_and_symlink_are_rejected_even_with_overwrite(self):
        with TemporaryDirectory() as directory:
            source=self.fixture(directory)
            hard=Path(directory)/'hard.json';os.link(source,hard)
            symbolic=Path(directory)/'symbolic.json';symbolic.symlink_to(source)
            original=source.read_bytes()
            for output in (source,hard,symbolic):
                with self.subTest(output=output): self.assert_preflight_rejected(source,output,overwrite=True)
            self.assertEqual(source.read_bytes(),original)

    def test_fixed_benchmark_hardlink_aliases_remain_protected_for_custom_input(self):
        with TemporaryDirectory(dir=ROOT) as directory:
            source=self.fixture(directory)
            hashes={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in FIXED_BENCHMARKS}
            for index, fixture in enumerate(FIXED_BENCHMARKS):
                alias=Path(directory)/f'fixed-alias-{index}.json';os.link(fixture,alias)
                self.assert_preflight_rejected(source,alias,overwrite=True)
            self.assertEqual({p:hashlib.sha256(p.read_bytes()).hexdigest() for p in FIXED_BENCHMARKS},hashes)

    def test_protected_nonjson_missing_parent_and_directory_outputs_reject_before_calls(self):
        with TemporaryDirectory() as directory:
            source=self.fixture(directory)
            folder=Path(directory)/'folder.json';folder.mkdir()
            for output in (ROOT/'learning'/'m11-not-created.json', Path(directory)/'report.txt',
                           Path(directory)/'absent'/'report.json',folder):
                with self.subTest(output=output): self.assert_preflight_rejected(source,output)
            self.assertFalse((ROOT/'learning'/'m11-not-created.json').exists())

    def test_existing_report_requires_explicit_overwrite(self):
        with TemporaryDirectory() as directory, ExitStack() as stack:
            source=self.fixture(directory);target=Path(directory)/'report.json';target.write_text('sentinel')
            self.assert_preflight_rejected(source,target)
            self.assertEqual(target.read_text(),'sentinel')
            self.mocks(stack)
            call_command('evaluate_retrieval',benchmark_file=source,output=target,overwrite=True,stdout=StringIO())
            self.assertEqual(json.loads(target.read_text())['benchmark_version'],'safety-regression')
            self.assertFalse(list(Path(directory).glob('.tutor-evaluation-*.tmp')))

    def test_alias_created_during_retrieval_is_rechecked_before_write(self):
        with TemporaryDirectory() as directory, ExitStack() as stack:
            source=self.fixture(directory);target=Path(directory)/'report.json';original=source.read_bytes()
            self.mocks(stack)
            def create_alias(query,limit):
                os.link(source,target)
                return []
            stack.enter_context(patch('learning.retrieval.retrieve_context',side_effect=create_alias))
            with self.assertRaises(CommandError):
                call_command('evaluate_retrieval',benchmark_file=source,output=target,overwrite=True,stdout=StringIO())
            self.assertEqual(source.read_bytes(),original)
            self.assertTrue(os.path.samefile(source,target))

    def test_fixture_byte_case_and_query_bounds_fail_before_retrieval(self):
        with TemporaryDirectory() as directory:
            source=self.fixture(directory)
            source.write_bytes(b' '*(MAX_FIXTURE_BYTES+1))
            self.assert_preflight_rejected(source)
            source=self.fixture(directory,[{'id':str(i),'split':'dev','category':'negative','query':'x','expected_terms':[]} for i in range(201)])
            self.assert_preflight_rejected(source)
            source=self.fixture(directory,[{'id':'long','split':'dev','category':'negative','query':'x'*501,'expected_terms':[]}])
            self.assert_preflight_rejected(source)

    def test_custom_input_and_explicit_builtin_version_are_mutually_exclusive(self):
        with TemporaryDirectory() as directory:
            source=self.fixture(directory)
            self.assert_preflight_rejected(source,benchmark_version='1')

    def test_default_builtin_one_and_version_two_work_without_output(self):
        for options in ({},{'benchmark_version':'2'}):
            with self.subTest(options=options), ExitStack() as stack:
                fixture={'version':'builtin','cases':[{'id':'dev','split':'dev','category':'negative','query':'example','expected_terms':[]}]}
                stack.enter_context(patch('learning.management.commands.evaluate_retrieval.load_benchmark',return_value=fixture))
                retrievers=self.mocks(stack,[])
                output=StringIO();call_command('evaluate_retrieval',stdout=output,**options)
                for retriever in retrievers: retriever.assert_called_once_with('example',limit=3)
                self.assertIn('not independent holdout',output.getvalue())
                self.assertNotIn('Đã ghi kết quả',output.getvalue())

    def test_description_mode_measures_candidates_without_automatic_baselines(self):
        with TemporaryDirectory() as directory,ExitStack() as stack:
            source=self.fixture(directory)
            target=Path(directory)/'description.json'
            retrievers=self.mocks(stack,retrieved=[{'term':'bank','meaning_vi':'ngân hàng','match_type':'description'}])
            call_command('evaluate_retrieval',benchmark_file=source,output=target,retrieval_mode='description',stdout=StringIO())
            report=json.loads(target.read_text())
            self.assertEqual(report['retrieval_mode'],'description')
            self.assertNotIn('baseline',report);self.assertNotIn('previous',report)
            self.assertIn('candidate retrieval only',report['scope'])
            self.assertEqual(report['improved']['overall']['sense_recall_at_3'],1)
            self.assertEqual(report['retriever_sha256']['description_index'],hashlib.sha256((ROOT/'learning/retrieval_description.py').read_bytes()).hexdigest())
            retrievers[0].assert_not_called();retrievers[1].assert_not_called()
            retrievers[2].assert_called_once_with('What does bank mean?',limit=3,retrieval_mode='description')

    def test_description_mode_rejects_nonvocabulary_gold_source(self):
        LearningContent.objects.filter(pk=self.content.pk).update(content_type='reading')
        with TemporaryDirectory() as directory:
            source=self.fixture(directory)
            with patch('learning.retrieval.retrieve_context') as retrieve:
                with self.assertRaises(CommandError):
                    call_command('evaluate_retrieval',benchmark_file=source,retrieval_mode='description',stdout=StringIO())
                retrieve.assert_not_called()
