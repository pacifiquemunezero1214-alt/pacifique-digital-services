
from pathlib import Path
import shutil

app_file = Path("app.py")
source = app_file.read_text(encoding="utf-8")

anchor = "# =========================================================\n# LOGIN MANAGER\n# ========================================================="

if anchor not in source:
    raise SystemExit("ERROR: LOGIN MANAGER anchor not found. No changes made.")

if "class NewsletterSubscription" in source:
    raise SystemExit("Newsletter models already exist. No changes made.")

models = '''
# =========================================================
# NEWSLETTER DATABASE MODELS
# =========================================================

class NewsletterSubscription(db.Model):
    __tablename__ = "newsletter_subscriptions"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        unique=True,
        index=True
    )

    email = db.Column(db.String(120), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    unsubscribe_token = db.Column(
        db.String(100),
        unique=True,
        nullable=False,
        index=True
    )

    consent_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    user = db.relationship("User", backref="newsletter_subscription")


class NewsletterIssue(db.Model):
    __tablename__ = "newsletter_issues"

    id = db.Column(db.Integer, primary_key=True)

    issue_date = db.Column(
        db.Date,
        nullable=False,
        unique=True,
        index=True
    )

    title = db.Column(db.String(200), nullable=False)

    company_updates = db.Column(db.Text, default="")
    job_connect_alerts = db.Column(db.Text, default="")
    business_technology_tips = db.Column(db.Text, default="")
    important_announcements = db.Column(db.Text, default="")

    status = db.Column(db.String(30), default="Draft", nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    published_at = db.Column(db.DateTime, nullable=True)


class NewsletterDelivery(db.Model):
    __tablename__ = "newsletter_deliveries"

    id = db.Column(db.Integer, primary_key=True)

    subscriber_id = db.Column(
        db.Integer,
        db.ForeignKey("newsletter_subscriptions.id"),
        nullable=False,
        index=True
    )

    issue_id = db.Column(
        db.Integer,
        db.ForeignKey("newsletter_issues.id"),
        nullable=False,
        index=True
    )

    status = db.Column(db.String(30), default="Pending", nullable=False)
    sent_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, default="")

    subscriber = db.relationship("NewsletterSubscription")
    issue = db.relationship("NewsletterIssue")

    __table_args__ = (
        db.UniqueConstraint(
            "subscriber_id",
            "issue_id",
            name="unique_newsletter_delivery"
        ),
    )


'''

backup_file = Path("app.py.newsletter-backup")
shutil.copy2(app_file, backup_file)

updated = source.replace(anchor, models + anchor, 1)
app_file.write_text(updated, encoding="utf-8")

print("SUCCESS: Newsletter models added.")
print("Backup created:", backup_file)
