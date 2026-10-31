
from getpass import getpass
from app import app, db, User

phone = "0732438879"

password = getpass("Enter new Manager password: ")
confirm = getpass("Confirm new password: ")

if len(password) < 12:
    print("Password must be at least 12 characters.")
    raise SystemExit

if password != confirm:
    print("Passwords do not match.")
    raise SystemExit

with app.app_context():
    manager = User.query.filter_by(role="manager").first()

    if not manager:
        print("Manager account not found.")
        raise SystemExit

    existing = User.query.filter_by(phone=phone).first()

    if existing and existing.id != manager.id:
        print("This phone number belongs to another account.")
        raise SystemExit

    manager.phone = phone
    manager.set_password(password)
    db.session.commit()

    print("SUCCESS: Manager phone and password updated.")
