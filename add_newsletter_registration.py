
from pathlib import Path
import shutil

app_file = Path("app.py")
source = app_file.read_text(encoding="utf-8")

old = '''            db.session.add(new_user)
            db.session.commit()
'''

new = '''            db.session.add(new_user)
            db.session.flush()

            # Subscribe only when the user explicitly opts in.
            newsletter_opt_in = (
                request.form.get("newsletter_opt_in") == "on"
            )

            if newsletter_opt_in:
                subscription = NewsletterSubscription(
                    user_id=new_user.id,
                    email=new_user.email,
                    active=True,
                    unsubscribe_token=uuid.uuid4().hex
                )
                db.session.add(subscription)

            db.session.commit()
'''

if old not in source:
    raise SystemExit("ERROR: Registration insertion point not found. No changes made.")

if "newsletter_opt_in = (" in source:
    raise SystemExit("Newsletter registration code already exists. No changes made.")

backup = Path("app.py.newsletter-registration-backup")
shutil.copy2(app_file, backup)

app_file.write_text(source.replace(old, new, 1), encoding="utf-8")

print("SUCCESS: Registration newsletter opt-in added.")
print("Backup created:", backup)
