from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('learning', '0021_weak_word_outcomes')]

    operations = [
        migrations.AddField(model_name='flashcard', name='is_available',
            field=models.BooleanField(default=True, db_index=True, verbose_name='Cho phép học thẻ',
                help_text='Tắt để tạm giữ riêng thẻ khỏi phiên học mới; không xóa lịch sử đã nộp.')),
        migrations.AddField(model_name='flashcard', name='availability_note',
            field=models.CharField(max_length=240, blank=True, verbose_name='Ghi chú tạm giữ',
                help_text='Lý do tạm giữ hoặc nội dung cần rà soát trước khi cho học lại.')),
    ]
