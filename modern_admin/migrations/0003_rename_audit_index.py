from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("modern_admin", "0002_savedview")]
    operations = [
        migrations.RenameIndex(
            model_name="auditevent",
            old_name="modern_admi_resourc_a284e0_idx",
            new_name="modern_admi_resourc_e93041_idx",
        )
    ]
