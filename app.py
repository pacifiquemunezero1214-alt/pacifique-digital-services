
import os
import re
import uuid
import smtplib
import io
import mimetypes
from functools import wraps
from email.message import EmailMessage
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, redirect, url_for,
        flash, abort, send_from_directory, Response, send_file
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user,
    login_required, logout_user, current_user
)
from sqlalchemy import inspect, text, or_
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

load_dotenv()

# =========================================================
# APPLICATION CONFIGURATION
# =========================================================

app = Flask(__name__)
os.makedirs(app.instance_path, exist_ok=True)

database_url = os.getenv("DATABASE_URL", "").strip()

if database_url.startswith("postgres://"):
    database_url = database_url.replace(
        "postgres://", "postgresql+psycopg2://", 1
    )
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace(
        "postgresql://", "postgresql+psycopg2://", 1
    )

app.config["SECRET_KEY"] = (
    os.getenv("SECRET_KEY")
    or "development-only-change-this-secret"
)

app.config["SQLALCHEMY_DATABASE_URI"] = (
    database_url
    or "sqlite:///" + os.path.join(
        app.instance_path, "pacifique_services.db"
    )
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "").strip()
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", "587"))
app.config["MAIL_USE_TLS"] = (
    os.getenv("MAIL_USE_TLS", "true").lower() == "true"
)
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME", "").strip()
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD", "")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv(
    "MAIL_DEFAULT_SENDER",
    os.getenv("MAIL_USERNAME", "")
).strip()

# Manual payment configuration
app.config["PAYMENT_PHONE"] = "0798386664"
app.config["PAYMENT_RECIPIENT"] = "Pacifique MUNEZERO"

# Payment proof upload configuration
# Maximum upload size: 25 MB
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

# Private storage for completed service results
SERVICE_RESULTS_FOLDER = os.path.join(
    app.instance_path, "service_results"
)
os.makedirs(SERVICE_RESULTS_FOLDER, exist_ok=True)

ALLOWED_RESULT_EXTENSIONS = {
    "pdf", "png", "jpg", "jpeg", "webp",
    "doc", "docx", "xls", "xlsx", "txt"
}

PAYMENT_PROOF_FOLDER = os.path.join(
    app.instance_path, "payment_proofs"
)
os.makedirs(PAYMENT_PROOF_FOLDER, exist_ok=True)

ALLOWED_PROOF_EXTENSIONS = {
    "png", "jpg", "jpeg", "webp"
}

PAYMENT_METHODS = ["MTN MoMo", "Airtel Money"]

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)


# =========================================================
# DATABASE MODELS
# =========================================================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(30), nullable=True, index=True)
    email = db.Column(db.String(120), unique=True, nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="user", nullable=False)

    is_active = db.Column(
        db.Boolean, default=True, nullable=False
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, default="")
    price = db.Column(db.Float, default=0)
    is_active = db.Column(db.Boolean, default=True)


class ServiceRequest(db.Model):
    __tablename__ = "service_request"

    id = db.Column(db.Integer, primary_key=True)

    owner_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True
    )

    customer_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=True,
        index=True
    )

    customer_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    email = db.Column(db.String(120), default="")
    service_name = db.Column(db.String(120), nullable=False)
    title = db.Column(db.String(180), nullable=False)
    details = db.Column(db.Text, nullable=False)
    priority = db.Column(db.String(20), default="Normal")
    status = db.Column(db.String(40), default="New")
    quoted_price = db.Column(db.Float, default=0)
    amount_paid = db.Column(db.Float, default=0)
    staff_notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ServiceResult(db.Model):
    __tablename__ = "service_result"

    id = db.Column(db.Integer, primary_key=True)

    request_id = db.Column(
        db.Integer,
        db.ForeignKey("service_request.id"),
        nullable=False,
        index=True
    )

    owner_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True
    )

    customer_user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=True,
        index=True
    )

    original_filename = db.Column(
        db.String(255),
        nullable=False
    )

    stored_filename = db.Column(
        db.String(255),
        nullable=False,
        unique=True
    )

    description = db.Column(db.Text, default="")

    uploaded_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    service_request = db.relationship("ServiceRequest")
class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    request_id = db.Column(
        db.Integer, db.ForeignKey("service_request.id"), nullable=False
    )

    amount = db.Column(db.Float, nullable=False)
    method = db.Column(db.String(50), default="Cash")
    reference = db.Column(db.String(120), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Pending, Approved or Rejected
    status = db.Column(
        db.String(30), default="Pending", nullable=False
    )

    # Uploaded payment screenshot
    proof_filename = db.Column(db.String(255), default="")

    # Verification information
    verified_at = db.Column(db.DateTime, nullable=True)
    verified_by = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=True
    )

    rejection_reason = db.Column(db.Text, default="")

    service_request = db.relationship("ServiceRequest")

# =========================================================
# JOB CONNECT DATABASE MODELS
# =========================================================

class JobSeekerProfile(db.Model):
    __tablename__ = "job_seeker_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        unique=True,
        index=True
    )

    professional_title = db.Column(db.String(150), default="")
    bio = db.Column(db.Text, default="")
    skills = db.Column(db.Text, default="")
    education = db.Column(db.Text, default="")
    experience = db.Column(db.Text, default="")
    preferred_location = db.Column(db.String(150), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    user = db.relationship("User", backref="job_seeker_profile")


class EmployerProfile(db.Model):
    __tablename__ = "employer_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        unique=True,
        index=True
    )

    company_name = db.Column(db.String(180), nullable=False)
    company_description = db.Column(db.Text, default="")
    industry = db.Column(db.String(120), default="")
    website = db.Column(db.String(255), default="")
    contact_phone = db.Column(db.String(30), default="")
    whatsapp_public = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    user = db.relationship("User", backref="employer_profile")


class JobListing(db.Model):
    __tablename__ = "job_listings"

    id = db.Column(db.Integer, primary_key=True)

    employer_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True
    )

    title = db.Column(db.String(180), nullable=False)
    company_name = db.Column(db.String(180), nullable=False)
    category = db.Column(db.String(120), default="")
    location = db.Column(db.String(180), default="")
    employment_type = db.Column(db.String(60), default="Full-time")
    salary = db.Column(db.String(120), default="")
    description = db.Column(db.Text, nullable=False)
    requirements = db.Column(db.Text, default="")
    application_deadline = db.Column(db.Date, nullable=True)

    # Open, Closed or Filled
    status = db.Column(
        db.String(30),
        default="Open",
        nullable=False,
        index=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        index=True
    )

    employer = db.relationship("User", backref="published_jobs")


class JobApplication(db.Model):
    __tablename__ = "job_applications"

    id = db.Column(db.Integer, primary_key=True)

    job_id = db.Column(
        db.Integer,
        db.ForeignKey("job_listings.id"),
        nullable=False,
        index=True
    )

    applicant_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True
    )

    cover_letter = db.Column(db.Text, default="")

    # Submitted, Reviewing, Shortlisted, Rejected or Accepted
    status = db.Column(
        db.String(30),
        default="Submitted",
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    job = db.relationship(
        "JobListing",
        backref=db.backref(
            "applications",
            lazy=True,
            cascade="all, delete-orphan"
        )
    )

    applicant = db.relationship(
        "User",
        backref="job_applications"
    )

    __table_args__ = (
        db.UniqueConstraint(
            "job_id",
            "applicant_id",
            name="unique_job_application"
        ),
    )




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

# ==========================================================
# PACIFIQUE DIGITAL SERVICES - ONLINE QUIZ SYSTEM
# ==========================================================

class QuizExam(db.Model):
    __tablename__ = "quiz_exams"

    id = db.Column(db.Integer, primary_key=True)
    creator_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    instructions = db.Column(db.Text)
    password_hash = db.Column(db.String(255), nullable=False)
    start_at = db.Column(db.DateTime, nullable=False)  # UTC
    end_at = db.Column(db.DateTime, nullable=False)    # UTC
    pass_mark = db.Column(db.Float, default=50)
    status = db.Column(db.String(20), default="Draft")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    questions = db.relationship(
        "QuizQuestion",
        backref="exam",
        cascade="all, delete-orphan",
        lazy=True
    )


class QuizQuestion(db.Model):
    __tablename__ = "quiz_questions"

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("quiz_exams.id"), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    marks = db.Column(db.Float, default=1)
    position = db.Column(db.Integer, default=0)

    options = db.relationship(
        "QuizOption",
        backref="question",
        cascade="all, delete-orphan",
        lazy=True
    )


class QuizOption(db.Model):
    __tablename__ = "quiz_options"

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(
        db.Integer,
        db.ForeignKey("quiz_questions.id"),
        nullable=False
    )
    option_text = db.Column(db.Text, nullable=False)
    is_correct = db.Column(db.Boolean, default=False)
    position = db.Column(db.Integer, default=0)


class QuizAttempt(db.Model):
    __tablename__ = "quiz_attempts"

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("quiz_exams.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    started_at = db.Column(db.DateTime)
    submitted_at = db.Column(db.DateTime)
    score = db.Column(db.Float, default=0)
    status = db.Column(db.String(30), default="In Progress")
    review_status = db.Column(db.String(20), default="Pending")
    review_reason = db.Column(db.Text)

    answers = db.relationship(
        "QuizAnswer",
        backref="attempt",
        cascade="all, delete-orphan",
        lazy=True
    )
events = db.relationship(
    "QuizEvent",
    backref="attempt",
    cascade="all, delete-orphan",
    lazy=True
)

class QuizAnswer(db.Model):
    __tablename__ = "quiz_answers"

    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(
        db.Integer,
        db.ForeignKey("quiz_attempts.id"),
        nullable=False
    )
    question_id = db.Column(
        db.Integer,
        db.ForeignKey("quiz_questions.id"),
        nullable=False
    )
    option_id = db.Column(db.Integer, db.ForeignKey("quiz_options.id"))
    awarded_marks = db.Column(db.Float, default=0)


class QuizEvent(db.Model):
    __tablename__ = "quiz_events"

    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(
        db.Integer,
        db.ForeignKey("quiz_attempts.id"),
        nullable=False
    )
    event_type = db.Column(db.String(80), nullable=False)
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
# ==========================================================
# PACIFIQUE DIGITAL SERVICES - LEARNING CENTER
# ==========================================================

class LearningMaterial(db.Model):
    __tablename__ = "learning_materials"

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    subject = db.Column(db.String(120), default="")
    material_type = db.Column(db.String(50), default="Notes")

    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)
    mimetype = db.Column(db.String(120), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)

    file_data = db.Column(db.LargeBinary, nullable=False)

    uploaded_by = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    is_published = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    uploader = db.relationship("User")
# ==========================================================
# USER HIDDEN LEARNING MATERIALS
# ==========================================================

class UserHiddenLearningMaterial(db.Model):
    __tablename__ = "user_hidden_learning_materials"

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        primary_key=True
    )

    material_id = db.Column(
        db.Integer,
        db.ForeignKey("learning_materials.id", ondelete="CASCADE"),
        primary_key=True
    )

    hidden_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

# ==========================================================
# ONLINE QUIZ - HELPER FUNCTIONS
# ==========================================================

def quiz_now_utc():
    """Use UTC as the authoritative server time."""
    return datetime.utcnow()


def quiz_kigali_to_utc(value):
    """Convert an Africa/Kigali local datetime input to UTC."""
    local_time = datetime.fromisoformat(value)
    return local_time - timedelta(hours=2)


def quiz_utc_to_kigali(value):
    """Convert a stored UTC datetime to Kigali local time."""
    if not value:
        return None
    return value + timedelta(hours=2)


def quiz_is_available(exam):
    """An exam is available only during its configured time window."""
    now = quiz_now_utc()
    return (
        exam.status == "Published"
        and exam.start_at <= now < exam.end_at
    )


def quiz_has_ended(exam):
    return quiz_now_utc() >= exam.end_at


def quiz_total_marks(exam):
    return sum(question.marks or 0 for question in exam.questions)


def quiz_log_event(attempt_id, event_type, details=None):
    event = QuizEvent(
        attempt_id=attempt_id,
        event_type=event_type,
        details=details
    )
    db.session.add(event)
    db.session.commit()




# =========================================================
# LOGIN MANAGER
# =========================================================

@login_manager.user_loader
def load_user(user_id):
    try:
        user = db.session.get(User, int(user_id))

        if user and user.is_active:
            return user

        return None

    except (ValueError, TypeError):
        return None


# =========================================================
# DATABASE MIGRATIONS
# =========================================================

def migrate_database():
    with db.engine.begin() as connection:
        inspector = inspect(connection)
        existing_tables = set(inspector.get_table_names())

        migrations = {
            "service": {
                "owner_id": "owner_id INTEGER REFERENCES user(id)"
            },
            "service_request": {
                "owner_id": "owner_id INTEGER REFERENCES user(id)",
                "customer_user_id": (
                    "customer_user_id INTEGER REFERENCES user(id)"
                ),
            },
            "payment": {
                "owner_id": "owner_id INTEGER REFERENCES user(id)",

                # Existing payments are preserved as approved.
                "status": (
                    "status VARCHAR(30) NOT NULL DEFAULT 'Approved'"
                ),
                "proof_filename": (
                    "proof_filename VARCHAR(255) DEFAULT ''"
                ),
                "verified_at": "verified_at TIMESTAMP",
                "verified_by": (
                    "verified_by INTEGER REFERENCES user(id)"
                ),
                "rejection_reason": "rejection_reason TEXT DEFAULT ''",
            },
            "user": {
                "full_name": "full_name VARCHAR(120)",
                "phone": "phone VARCHAR(30)",
                "email": "email VARCHAR(120)",
                "is_active": (
                    "is_active BOOLEAN NOT NULL DEFAULT TRUE"
                ),
            },
        }

        for table_name, column_migrations in migrations.items():
            if table_name not in existing_tables:
                continue

            columns = {
                column["name"]
                for column in inspect(connection).get_columns(table_name)
            }

            for column_name, column_sql in column_migrations.items():
                if column_name not in columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE {table_name} "
                            f"ADD COLUMN {column_sql}"
                        )
                    )
                    columns.add(column_name)

        configured_admin_email = (
            os.getenv("ADMIN_EMAIL", "").strip().lower()
        )

        if configured_admin_email and "user" in existing_tables:
            connection.execute(
                text(
                    'UPDATE "user" SET email = :email '
                    "WHERE role IN ('manager', 'admin') "
                    "AND (email IS NULL OR email = '') "
                    "AND username = :username"
                ),
                {
                    "email": configured_admin_email,
                    "username": os.getenv("ADMIN_USERNAME", "manager"),
                },
            )


# =========================================================
# ROLE AND ACCESS HELPERS
# =========================================================

def is_manager():
    return (
        current_user.is_authenticated
        and current_user.role in ("manager", "admin")
    )


def manager_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))

        if not current_user.is_active:
            logout_user()
            flash("Your account is inactive.", "error")
            return redirect(url_for("login"))

        if not is_manager():
            abort(403)

        return view_function(*args, **kwargs)

    return wrapped_view


def owned_requests_query():
    query = ServiceRequest.query

    if is_manager():
        query = query.filter_by(owner_id=current_user.id)
    else:
        query = query.filter_by(owner_id=current_user.id)

    return query


def owned_services_query():
    return Service.query.filter_by(owner_id=current_user.id)


def owned_payments_query():
    return Payment.query.filter_by(owner_id=current_user.id)


def get_request_or_404(request_id):
    service_request = db.get_or_404(ServiceRequest, request_id)

    if service_request.owner_id != current_user.id:
        abort(404)

    return service_request


def customer_requests_query(user):
    conditions = [
        ServiceRequest.customer_user_id == user.id
    ]

    if user.phone:
        conditions.append(ServiceRequest.phone == user.phone)

    if user.email:
        conditions.append(
            db.func.lower(ServiceRequest.email) == user.email.lower()
        )

    return ServiceRequest.query.filter(or_(*conditions))


def get_customer_request_or_404(request_id):
    service_request = customer_requests_query(
        current_user
    ).filter(
        ServiceRequest.id == request_id
    ).first()

    if not service_request:
        abort(404)

    return service_request


def approved_payments_total(query):
    return query.filter(
        Payment.status == "Approved"
    )


def remaining_amount(service_request):
    return max(
        0,
        float(service_request.quoted_price or 0)
        - float(service_request.amount_paid or 0)
    )


def allowed_proof_file(filename):
    if not filename or "." not in filename:
        return False

    extension = filename.rsplit(".", 1)[1].lower()
    return extension in ALLOWED_PROOF_EXTENSIONS


def save_payment_proof(file):
    if not file or not file.filename:
        return None

    if not allowed_proof_file(file.filename):
        return None

    original_name = secure_filename(file.filename)
    extension = original_name.rsplit(".", 1)[1].lower()

    unique_filename = (
        uuid.uuid4().hex + "." + extension
    )

    file_path = os.path.join(
        PAYMENT_PROOF_FOLDER,
        unique_filename
    )

    file.save(file_path)

    return unique_filename
def allowed_result_file(filename):
    if not filename or "." not in filename:
        return False

    extension = filename.rsplit(".", 1)[1].lower()
    return extension in ALLOWED_RESULT_EXTENSIONS


def save_service_result(file):
    if not file or not file.filename:
        return None

    if not allowed_result_file(file.filename):
        return None

    original_name = secure_filename(file.filename)

    if not original_name:
        return None

    extension = original_name.rsplit(".", 1)[1].lower()
    stored_name = f"{uuid.uuid4().hex}.{extension}"

    file_path = os.path.join(
        SERVICE_RESULTS_FOLDER,
        stored_name
    )

    file.save(file_path)

    return stored_name


# =========================================================
# AUTHENTICATION HELPERS
# =========================================================

def password_is_strong(password):
    return (
        len(password) >= 8
        and re.search(r"[A-Z]", password) is not None
        and re.search(r"[^A-Za-z0-9]", password) is not None
    )


def normalized_email(value):
    return (value or "").strip().lower()


def email_looks_valid(value):
    return re.fullmatch(
        r"[^\s@]+@[^\s@]+\.[^\s@]+", value or ""
    ) is not None



def send_password_reset_email(user, reset_url):
    api_key = os.getenv("RESEND_API_KEY")
    sender = os.getenv(
        "RESEND_FROM_EMAIL",
        "onboarding@resend.dev"
    )

    if not api_key:
        app.logger.error("RESEND_API_KEY is missing.")
        return False

    try:
        import resend

        resend.api_key = api_key

        params = {
            "from": sender,
            "to": [user.email],
            "subject": "Reset your Pacifique Digital Services password",
            "text": (
                f"Hello {user.full_name or user.username},\n\n"
                "We received a request to reset your password.\n"
                "Use the link below to choose a new password. "
                "It expires in 1 hour.\n\n"
                f"{reset_url}\n\n"
                "If you did not request this, ignore this email.\n"
            )
        }

        resend.Emails.send(params)
        app.logger.info("Password reset email sent successfully.")
        return True

    except Exception:
        app.logger.exception(
            "Could not send password reset email through Resend."
        )
        return False

# ==========================================================
# LEARNING CENTER - MANAGER AND USER ROUTES
# ==========================================================

ALLOWED_LEARNING_EXTENSIONS = {
    "pdf", "doc", "docx", "ppt", "pptx",
    "xls", "xlsx", "txt", "csv",
    "jpg", "jpeg", "png", "webp"
}

MAX_LEARNING_FILE_SIZE = 10 * 1024 * 1024  # 10 MB per file


def allowed_learning_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_LEARNING_EXTENSIONS
    )


@app.route("/manager/learning-materials", methods=["GET", "POST"])
@login_required
@manager_required
def manager_learning_materials():

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        subject = request.form.get("subject", "").strip()
        material_type = request.form.get("material_type", "Notes").strip()

        files = request.files.getlist("files")

        if not title:
            flash("Please enter a title for these materials.", "danger")
            return redirect(url_for("manager_learning_materials"))

        files = [f for f in files if f and f.filename]

        if not files:
            flash("Please select at least one file.", "danger")
            return redirect(url_for("manager_learning_materials"))

        if len(files) > 20:
            flash("You can upload a maximum of 20 files at once.", "danger")
            return redirect(url_for("manager_learning_materials"))

        materials_to_save = []

        for uploaded_file in files:
            original_filename = secure_filename(uploaded_file.filename)

            if not original_filename or not allowed_learning_file(original_filename):
                flash(
                    f"Unsupported file type: {uploaded_file.filename}",
                    "danger"
                )
                return redirect(url_for("manager_learning_materials"))

            file_data = uploaded_file.read()

            if not file_data:
                flash(f"{original_filename} is empty.", "danger")
                return redirect(url_for("manager_learning_materials"))

            if len(file_data) > MAX_LEARNING_FILE_SIZE:
                flash(
                    f"{original_filename} exceeds the 10 MB limit.",
                    "danger"
                )
                return redirect(url_for("manager_learning_materials"))

            extension = original_filename.rsplit(".", 1)[1].lower()
            stored_filename = f"{uuid.uuid4().hex}.{extension}"

            mimetype = (
                uploaded_file.mimetype
                or mimetypes.guess_type(original_filename)[0]
                or "application/octet-stream"
            )

            material = LearningMaterial(
                title=title,
                description=description,
                subject=subject,
                material_type=material_type,
                original_filename=original_filename,
                stored_filename=stored_filename,
                mimetype=mimetype,
                file_size=len(file_data),
                file_data=file_data,
                uploaded_by=current_user.id,
                is_published=True
            )

            materials_to_save.append(material)

        try:
            db.session.add_all(materials_to_save)
            db.session.commit()

            flash(
                f"Successfully published {len(materials_to_save)} file(s).",
                "success"
            )

        except Exception:
            db.session.rollback()
            app.logger.exception("Learning materials upload failed.")
            flash("Upload failed. Please try again.", "danger")

        return redirect(url_for("manager_learning_materials"))

    materials = LearningMaterial.query.order_by(
        LearningMaterial.created_at.desc()
    ).all()

    return render_template(
        "manager_learning_materials.html",
        materials=materials
    )
@app.route("/learning-materials/<int:material_id>/hide", methods=["POST"])
@login_required
def hide_learning_material(material_id):

    material = LearningMaterial.query.get_or_404(material_id)

    if not material.is_published and not is_manager():
        abort(404)

    already_hidden = UserHiddenLearningMaterial.query.filter_by(
        user_id=current_user.id,
        material_id=material.id
    ).first()

    if not already_hidden:
        hidden_item = UserHiddenLearningMaterial(
            user_id=current_user.id,
            material_id=material.id
        )
        db.session.add(hidden_item)
        db.session.commit()

    flash("Material removed from your Learning Center.", "success")

    return redirect(url_for("learning_center"))

@app.route("/learning-center")
@login_required
def learning_center():

    search = request.args.get("search", "").strip()
    material_type = request.args.get("type", "").strip()

    hidden_material_ids = db.session.query(
        UserHiddenLearningMaterial.material_id
    ).filter_by(
        user_id=current_user.id
    ).subquery()

    query = LearningMaterial.query.filter(
        LearningMaterial.is_published == True,
        ~LearningMaterial.id.in_(hidden_material_ids)
    )

    if search:
        query = query.filter(
            or_(
                LearningMaterial.title.ilike(f"%{search}%"),
                LearningMaterial.subject.ilike(f"%{search}%"),
                LearningMaterial.description.ilike(f"%{search}%")
            )
        )

    if material_type:
        query = query.filter_by(material_type=material_type)

    materials = query.order_by(
        LearningMaterial.created_at.desc()
    ).all()

    return render_template(
        "learning_center.html",
        materials=materials,
        search=search,
        selected_type=material_type
    )

@app.route("/learning-materials/<int:material_id>/view")
@login_required
def view_learning_material(material_id):

    material = LearningMaterial.query.get_or_404(material_id)

    if not material.is_published and not is_manager():
        abort(404)
    if not is_manager():
        hidden_item = UserHiddenLearningMaterial.query.filter_by(
            user_id=current_user.id,
            material_id=material.id
        ).first()

        if hidden_item:
            abort(404)

    if material.mimetype not in (
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp"
    ):
        return redirect(
            url_for("download_learning_material", material_id=material.id)
        )

    response = send_file(
        io.BytesIO(material.file_data),
        mimetype=material.mimetype,
        as_attachment=False,
        download_name=material.original_filename
    )

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"

    return response


@app.route("/learning-materials/<int:material_id>/download")
@login_required
def download_learning_material(material_id):

    material = LearningMaterial.query.get_or_404(material_id)

    if not material.is_published and not is_manager():
        abort(404)
    if not is_manager():
        hidden_item = UserHiddenLearningMaterial.query.filter_by(
            user_id=current_user.id,
            material_id=material.id
        ).first()

        if hidden_item:
            abort(404)

    response = send_file(
        io.BytesIO(material.file_data),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=material.original_filename
    )

    response.headers["X-Content-Type-Options"] = "nosniff"

    return response

# ==========================================================
# ONLINE QUIZ - MANAGER ROUTES
# ==========================================================

@app.route("/manager/quizzes", methods=["GET"])
@login_required
@manager_required
def manager_quizzes():
    exams = QuizExam.query.order_by(QuizExam.created_at.desc()).all()
    return render_template("manager_quizzes.html", exams=exams)


@app.route("/manager/quizzes/create", methods=["GET", "POST"])
@login_required
@manager_required
def create_quiz():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        instructions = request.form.get("instructions", "").strip()
        password = request.form.get("password", "")
        start_value = request.form.get("start_at", "")
        end_value = request.form.get("end_at", "")
        pass_mark = request.form.get("pass_mark", "50")

        if not all([title, password, start_value, end_value]):
            flash("Please complete all required fields.", "danger")
            return redirect(url_for("create_quiz"))

        try:
            start_at = quiz_kigali_to_utc(start_value)
            end_at = quiz_kigali_to_utc(end_value)
            pass_mark = float(pass_mark)
        except (ValueError, TypeError):
            flash("Please enter valid dates and pass mark.", "danger")
            return redirect(url_for("create_quiz"))

        if end_at <= start_at:
            flash("Exam end time must be after its start time.", "danger")
            return redirect(url_for("create_quiz"))

        if not 0 <= pass_mark <= 100:
            flash("Pass mark must be between 0 and 100.", "danger")
            return redirect(url_for("create_quiz"))

        exam = QuizExam(
            creator_id=current_user.id,
            title=title,
            instructions=instructions,
            password_hash=generate_password_hash(password),
            start_at=start_at,
            end_at=end_at,
            pass_mark=pass_mark,
            status="Draft"
        )

        db.session.add(exam)
        db.session.commit()

        flash("Quiz created successfully. Add questions before publishing.", "success")
        return redirect(url_for("manager_quizzes"))

    return render_template("create_quiz.html")


@app.route("/manager/quizzes/<int:exam_id>/publish", methods=["POST"])
@login_required
@manager_required
def publish_quiz(exam_id):
    exam = QuizExam.query.get_or_404(exam_id)

    if not exam.questions:
        flash("Add at least one question before publishing.", "danger")
        return redirect(url_for("manager_quizzes"))

    if exam.end_at <= exam.start_at:
        flash("The exam schedule is invalid.", "danger")
        return redirect(url_for("manager_quizzes"))

    exam.status = "Published"
    db.session.commit()

    flash("Quiz published successfully.", "success")
    return redirect(url_for("manager_quizzes"))


@app.route("/manager/quizzes/<int:exam_id>/close", methods=["POST"])
@login_required
@manager_required
def close_quiz(exam_id):
    exam = QuizExam.query.get_or_404(exam_id)
    exam.status = "Closed"
    db.session.commit()

    flash("Quiz closed.", "success")
    return redirect(url_for("manager_quizzes"))

# ==========================================================
# ONLINE QUIZ - ADD QUESTIONS
# ==========================================================

@app.route("/manager/quizzes/<int:exam_id>/questions", methods=["GET", "POST"])
@login_required
@manager_required
def manage_quiz_questions(exam_id):
    exam = QuizExam.query.get_or_404(exam_id)

    if exam.status != "Draft":
        flash("Questions can only be changed while the quiz is a draft.", "danger")
        return redirect(url_for("manager_quizzes"))

    if request.method == "POST":
        question_text = request.form.get("question_text", "").strip()
        options = [
            value.strip()
            for value in request.form.getlist("options")
            if value.strip()
        ]
        correct_option = request.form.get("correct_option", "")
        marks = request.form.get("marks", "1")

        if not question_text or len(options) < 2:
            flash("Enter a question and at least two options.", "danger")
            return redirect(url_for("manage_quiz_questions", exam_id=exam.id))

        try:
            marks = float(marks)
            correct_index = int(correct_option)

            if marks <= 0 or not 0 <= correct_index < len(options):
                raise ValueError
        except (ValueError, TypeError):
            flash("Enter valid marks and select the correct answer.", "danger")
            return redirect(url_for("manage_quiz_questions", exam_id=exam.id))

        question = QuizQuestion(
            exam_id=exam.id,
            question_text=question_text,
            marks=marks,
            position=len(exam.questions) + 1
        )

        db.session.add(question)
        db.session.flush()

        for index, option_text in enumerate(options):
            option = QuizOption(
                question_id=question.id,
                option_text=option_text,
                is_correct=(index == correct_index),
                position=index + 1
            )
            db.session.add(option)

        db.session.commit()

        flash("Question added successfully.", "success")
        return redirect(url_for("manage_quiz_questions", exam_id=exam.id))

    return render_template(
        "manage_quiz_questions.html",
        exam=exam
    )
# =========================================================
# USER ONLINE QUIZZES
# =========================================================
@app.route("/quizzes")
@login_required
def available_quizzes():
    exams = QuizExam.query.filter(
        QuizExam.status == "Published"
    ).order_by(QuizExam.start_at.asc()).all()

    now = quiz_now_utc()

    return render_template(
        "available_quizzes.html",
        exams=exams,
        now=now,
        quiz_utc_to_kigali=quiz_utc_to_kigali
    )

# =========================================================
# START ONLINE QUIZ
# =========================================================

@app.route("/quizzes/<int:exam_id>/start", methods=["GET", "POST"])
@login_required
def start_quiz(exam_id):
    exam = QuizExam.query.get_or_404(exam_id)
    now = quiz_now_utc()

    if exam.status != "Published":
        flash("This quiz is not available.", "danger")
        return redirect(url_for("available_quizzes"))

    if now < exam.start_at:
        flash("This quiz has not started yet.", "warning")
        return redirect(url_for("available_quizzes"))

    if now >= exam.end_at:
        flash("This quiz has already ended.", "danger")
        return redirect(url_for("available_quizzes"))

    existing_attempt = QuizAttempt.query.filter_by(
        exam_id=exam.id,
        user_id=current_user.id
    ).first()

    if existing_attempt:
        if existing_attempt.status == "In Progress":
            return redirect(
                url_for("take_quiz", attempt_id=existing_attempt.id)
            )

        flash("You have already submitted this quiz.", "info")
        return redirect(url_for("available_quizzes"))

    if request.method == "POST":
        password = request.form.get("password", "")

        if not check_password_hash(exam.password_hash, password):
            flash("Incorrect quiz password.", "danger")
            return redirect(url_for("start_quiz", exam_id=exam.id))

        attempt = QuizAttempt(
            exam_id=exam.id,
            user_id=current_user.id,
            started_at=now,
            status="In Progress",
            review_status="Pending"
        )

        db.session.add(attempt)
        db.session.commit()

        return redirect(
            url_for("take_quiz", attempt_id=attempt.id)
        )

    return render_template(
    "start_quiz.html",
    exam=exam,
    quiz_utc_to_kigali=quiz_utc_to_kigali
)


# =========================================================
# TAKE AND SUBMIT ONLINE QUIZ
# =========================================================

@app.route("/quizzes/attempt/<int:attempt_id>", methods=["GET", "POST"])
@login_required
def take_quiz(attempt_id):
    attempt = QuizAttempt.query.get_or_404(attempt_id)

    if attempt.user_id != current_user.id:
        abort(403)

    exam = QuizExam.query.get_or_404(attempt.exam_id)

    if attempt.status != "In Progress":
        flash("This quiz has already been submitted.", "info")
        return redirect(url_for("available_quizzes"))

    now = quiz_now_utc()

    if now >= exam.end_at:
        attempt.status = "Submitted"
        attempt.submitted_at = exam.end_at
        db.session.commit()
        flash("The quiz time has ended.", "warning")
        return redirect(url_for("available_quizzes"))

    if request.method == "POST":
        total_score = 0

        for question in exam.questions:
            selected_option_id = request.form.get(
                f"question_{question.id}"
            )

            if not selected_option_id:
                continue

            selected_option = QuizOption.query.filter_by(
                id=selected_option_id,
                question_id=question.id
            ).first()

            if not selected_option:
                continue

            awarded_marks = (
                question.marks if selected_option.is_correct else 0
            )

            answer = QuizAnswer(
                attempt_id=attempt.id,
                question_id=question.id,
                option_id=selected_option.id,
                awarded_marks=awarded_marks
            )

            db.session.add(answer)
            total_score += awarded_marks

        attempt.score = total_score
        attempt.status = "Submitted"
        attempt.submitted_at = quiz_now_utc()
        attempt.review_status = "Pending"

        db.session.commit()

        flash(
            f"Quiz submitted. Your score: "
            f"{total_score} / {quiz_total_marks(exam)}. "
            "Your result is awaiting review.",
            "success"
        )

        return redirect(url_for("available_quizzes"))

    questions = list(exam.questions)
    questions.sort(key=lambda item: uuid.uuid4().hex)

    quiz_items = []

    for question in questions:
        options = list(question.options)
        options.sort(key=lambda item: uuid.uuid4().hex)

        quiz_items.append({
            "question": question,
            "options": options
        })

    return render_template(
        "take_quiz.html",
        exam=exam,
        attempt=attempt,
        quiz_items=quiz_items,
        total_marks=quiz_total_marks(exam),
        quiz_utc_to_kigali=quiz_utc_to_kigali
    )

# =========================================================
# ONLINE QUIZ - SECURITY EVENT LOGGING
# =========================================================

@app.route(
    "/quizzes/attempt/<int:attempt_id>/event",
    methods=["POST"]
)
@login_required
def quiz_record_event(attempt_id):
    attempt = QuizAttempt.query.get_or_404(attempt_id)

    if attempt.user_id != current_user.id:
        abort(403)

    if attempt.status != "In Progress":
        return {"success": False, "message": "Attempt closed"}, 400

    exam = QuizExam.query.get_or_404(attempt.exam_id)

    if quiz_now_utc() >= exam.end_at:
        attempt.status = "Submitted"
        attempt.submitted_at = exam.end_at
        db.session.commit()
        return {"success": False, "message": "Exam ended"}, 400

    event_type = request.form.get("event_type", "unknown")
    allowed_events = {
        "tab_switch",
        "fullscreen_exit",
        "copy_attempt",
        "paste_attempt",
        "right_click"
    }

    if event_type not in allowed_events:
        return {"success": False, "message": "Invalid event"}, 400

    quiz_log_event(
        attempt.id,
        event_type,
        "Candidate security event recorded"
    )

    return {"success": True}, 200

# =========================================================
# ONLINE QUIZ - STUDENT RESULTS
# =========================================================

@app.route("/quiz-results")
@login_required
def quiz_results():
    attempts = QuizAttempt.query.filter_by(
        user_id=current_user.id
    ).order_by(QuizAttempt.started_at.desc()).all()

    results = []

    for attempt in attempts:
        exam = QuizExam.query.get(attempt.exam_id)
        if exam:
            results.append({
                "attempt": attempt,
                "exam": exam,
                "total_marks": quiz_total_marks(exam)
            })

    return render_template(
        "quiz_results.html",
        results=results
    )


# =========================================================
# ONLINE QUIZ - MANAGER PARTICIPANTS AND REVIEW
# =========================================================

@app.route("/manager/quizzes/<int:exam_id>/attempts")
@login_required
@manager_required
def manager_quiz_attempts(exam_id):
    exam = QuizExam.query.get_or_404(exam_id)

    attempts = QuizAttempt.query.filter_by(
        exam_id=exam.id
    ).order_by(QuizAttempt.started_at.desc()).all()

    attempt_rows = []

    for attempt in attempts:
        student = db.session.get(User, attempt.user_id)
        attempt_rows.append({
            "attempt": attempt,
            "student": student
        })

    return render_template(
        "manager_quiz_attempts.html",
        exam=exam,
        attempt_rows=attempt_rows,
        total_marks=quiz_total_marks(exam)
    )


@app.route(
    "/manager/quizzes/attempt/<int:attempt_id>/review",
    methods=["POST"]
)
@login_required
@manager_required
def review_quiz_attempt(attempt_id):
    attempt = QuizAttempt.query.get_or_404(attempt_id)

    if attempt.status != "Submitted":
        flash("Only submitted attempts can be reviewed.", "danger")
        return redirect(
            url_for(
                "manager_quiz_attempts",
                exam_id=attempt.exam_id
            )
        )

    decision = request.form.get("decision", "").strip()
    reason = request.form.get("reason", "").strip()

    if decision not in ("Approved", "Rejected"):
        flash("Invalid review decision.", "danger")
        return redirect(
            url_for(
                "manager_quiz_attempts",
                exam_id=attempt.exam_id
            )
        )

    if decision == "Rejected" and not reason:
        flash("Please provide a reason for rejection.", "danger")
        return redirect(
            url_for(
                "manager_quiz_attempts",
                exam_id=attempt.exam_id
            )
        )

    attempt.review_status = decision
    attempt.review_reason = reason if decision == "Rejected" else ""

    db.session.commit()

    flash("Quiz result review saved successfully.", "success")
    return redirect(
        url_for(
            "manager_quiz_attempts",
            exam_id=attempt.exam_id
        )
    )




# =========================================================
# PUBLIC HOME / LANDING PAGE
# =========================================================
@app.route("/robots.txt")
def robots_txt():
    return send_from_directory(
        app.static_folder,
        "robots.txt",
        mimetype="text/plain"
    )
@app.route("/ads.txt")
def ads_txt():
    return send_from_directory(
        app.static_folder,
        "ads.txt",
        mimetype="text/plain"
    )

@app.route("/")
def home():
    return render_template("landing.html")
@app.route("/sitemap.xml")
def sitemap():
    pages = [
        ("home", "weekly", "1.0"),
        ("about", "monthly", "0.8"),
        ("contact", "monthly", "0.8"),
        ("privacy_policy", "yearly", "0.3"),
    ]

    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]

    for endpoint, frequency, priority in pages:
        page_url = url_for(endpoint, _external=True)
        page_url = page_url.replace("http://", "https://", 1)

        xml.append("<url>")
        xml.append(f"<loc>{page_url}</loc>")
        xml.append(f"<changefreq>{frequency}</changefreq>")
        xml.append(f"<priority>{priority}</priority>")
        xml.append("</url>")

    xml.append("</urlset>")

    return Response("\n".join(xml), mimetype="application/xml")

# =========================================================
# PUBLIC CONTACT US
# =========================================================

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = normalized_email(request.form.get("email", ""))
        subject = request.form.get("subject", "").strip()
        message_body = request.form.get("message", "").strip()

        if not all([name, email, subject, message_body]):
            flash("Please complete all fields.", "error")
            return redirect(url_for("contact"))

        if (
            len(name) > 120
            or len(email) > 120
            or len(subject) > 180
            or len(message_body) > 5000
        ):
            flash("Some fields exceed the allowed length.", "error")
            return redirect(url_for("contact"))

        if not email_looks_valid(email):
            flash("Please enter a valid email address.", "error")
            return redirect(url_for("contact"))

        required_settings = (
            app.config["MAIL_SERVER"],
            app.config["MAIL_USERNAME"],
            app.config["MAIL_PASSWORD"],
            app.config["MAIL_DEFAULT_SENDER"],
        )

        if not all(required_settings):
            flash(
                "The contact form email service is not configured yet. "
                "Please contact us through WhatsApp or email.",
                "error",
            )
            return redirect(url_for("contact"))

        email_message = EmailMessage()
        email_message["Subject"] = (
            f"Contact Us: {subject[:180]}"
        )
        email_message["From"] = app.config["MAIL_DEFAULT_SENDER"]
        email_message["To"] = "pacifiquemunezero1214@gmail.com"
        email_message["Reply-To"] = email

        email_message.set_content(
            "New message from Pacifique Digital Services website\n\n"
            f"Name: {name}\n"
            f"Email: {email}\n"
            f"Subject: {subject}\n\n"
            f"Message:\n{message_body}\n"
        )

        try:
            with smtplib.SMTP(
                app.config["MAIL_SERVER"],
                app.config["MAIL_PORT"],
                timeout=20,
            ) as smtp:
                smtp.ehlo()

                if app.config["MAIL_USE_TLS"]:
                    smtp.starttls()
                    smtp.ehlo()

                smtp.login(
                    app.config["MAIL_USERNAME"],
                    app.config["MAIL_PASSWORD"],
                )
                smtp.send_message(email_message)

            flash(
                "Your message has been sent successfully. "
                "We will get back to you soon!",
                "success",
            )

        except (OSError, smtplib.SMTPException):
            app.logger.exception("Contact message delivery failed.")
            flash(
                "We could not send your message right now. "
                "Please contact us through WhatsApp or email.",
                "error",
            )

        return redirect(url_for("contact"))

    return render_template("contact.html")
# =========================================================
# PUBLIC ABOUT US
# =========================================================

@app.route("/about")
def about():
    return render_template("about.html")
# =========================================================
# PUBLIC PRIVACY POLICY
# =========================================================

@app.route("/privacy-policy")
def privacy_policy():
    return render_template("privacy.html")



# =========================================================
# REGISTRATION
# =========================================================

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = normalized_email(request.form.get("email", ""))
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not all([full_name, phone, email, password, confirm_password]):
            flash("Please fill in all required fields.", "error")
            return render_template("register.html")

        if len(full_name) > 120:
            flash("Full name must be 120 characters or fewer.", "error")
            return render_template("register.html")

        if len(phone) < 7 or len(phone) > 30:
            flash("Enter a valid phone number.", "error")
            return render_template("register.html")

        if not email_looks_valid(email) or len(email) > 120:
            flash("Enter a valid email address.", "error")
            return render_template("register.html")

        if not password_is_strong(password):
            flash(
                "Password must have at least 8 characters, "
                "one uppercase letter and one special character.",
                "error",
            )
            return render_template("register.html")

        if password != confirm_password:
            flash("The two passwords do not match.", "error")
            return render_template("register.html")

        existing_email = User.query.filter(
            db.func.lower(User.email) == email
        ).first()

        existing_username = User.query.filter(
            db.func.lower(User.username) == email
        ).first()

        existing_phone = User.query.filter_by(phone=phone).first()

        if existing_email or existing_username:
            flash("An account with this email already exists.", "error")
            return render_template("register.html")

        if existing_phone:
            flash("This phone number is already registered.", "error")
            return render_template("register.html")

        new_user = User(
            username=email,
            full_name=full_name,
            phone=phone,
            email=email,
            role="user",
            is_active=True,
        )
        new_user.set_password(password)

        try:
            db.session.add(new_user)
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

            flash(
                "Registration successful! Sign in using your phone number "
                "and password.",
                "success",
            )
            return redirect(url_for("login"))

        except Exception:
            db.session.rollback()
            app.logger.exception("Account registration failed")
            flash("Registration failed. Please try again.", "error")

    return render_template("register.html")


# =========================================================
# LOGIN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")

        if not phone or not password:
            flash("Enter your phone number and password.", "error")
            return render_template("login.html")

        user = User.query.filter_by(phone=phone).first()

        if user is None:
            old_manager = User.query.filter_by(username=phone).first()

            if (
                old_manager
                and old_manager.role in ("manager", "admin")
                and not old_manager.phone
            ):
                user = old_manager

        if user and user.check_password(password):
            if not user.is_active:
                flash(
                    "This account has been deactivated. Contact the manager.",
                    "error",
                )
                return render_template("login.html")

            login_user(user)
            flash("Welcome back!", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid phone number or password.", "error")

    return render_template("login.html")


# =========================================================
# FORGOT PASSWORD
# =========================================================

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = normalized_email(request.form.get("email", ""))

        if email and email_looks_valid(email):
            user = User.query.filter(
                db.func.lower(User.email) == email
            ).first()

            if user and user.is_active:
                serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])
                token = serializer.dumps(
                    user.id,
                    salt="pacifique-password-reset",
                )
                reset_url = url_for(
                    "reset_password",
                    token=token,
                    _external=True,
                )
                send_password_reset_email(user, reset_url)

        flash(
            "If the account exists and email delivery is configured, "
            "a password-reset link will be sent.",
            "success",
        )
        return redirect(url_for("forgot_password"))

    return render_template("forgot_password.html")


# =========================================================
# RESET PASSWORD
# =========================================================

@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])

    try:
        user_id = serializer.loads(
            token,
            salt="pacifique-password-reset",
            max_age=3600,
        )
    except SignatureExpired:
        flash("This reset link has expired. Request a new one.", "error")
        return redirect(url_for("forgot_password"))
    except BadSignature:
        flash("This reset link is invalid. Request a new one.", "error")
        return redirect(url_for("forgot_password"))

    user = db.session.get(User, int(user_id))

    if not user or not user.is_active:
        flash("This reset link is invalid. Request a new one.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not password_is_strong(password):
            flash(
                "Password must have at least 8 characters, "
                "one uppercase letter and one special character.",
                "error",
            )
            return render_template("reset_password.html", token=token)

        if password != confirm_password:
            flash("The two passwords do not match.", "error")
            return render_template("reset_password.html", token=token)

        user.set_password(password)
        db.session.commit()

        flash("Password reset successfully. You can now sign in.", "success")
        return redirect(url_for("login"))

    return render_template("reset_password.html", token=token)


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# =========================================================
# ROLE-BASED DASHBOARD
# =========================================================

@app.route("/dashboard")
@login_required
def dashboard():
    if not is_manager():
        return redirect(url_for("user_dashboard"))

    requests_query = ServiceRequest.query.filter_by(
        owner_id=current_user.id
    )

    total_requests = requests_query.count()
    new_requests = requests_query.filter_by(status="New").count()
    in_progress = requests_query.filter_by(status="In Progress").count()
    completed = requests_query.filter_by(status="Completed").count()

    total_payments = db.session.query(
        db.func.coalesce(db.func.sum(Payment.amount), 0)
    ).filter(
        Payment.owner_id == current_user.id,
        Payment.status == "Approved",
    ).scalar()

    recent_requests = requests_query.order_by(
        ServiceRequest.created_at.desc()
    ).limit(5).all()

    return render_template(
        "dashboard.html",
        total_requests=total_requests,
        new_requests=new_requests,
        in_progress=in_progress,
        completed=completed,
        total_payments=total_payments,
        recent_requests=recent_requests,
    )


@app.route("/user-dashboard")
@login_required
def user_dashboard():
    if is_manager():
        return redirect(url_for("dashboard"))

    requests_query = customer_requests_query(current_user)

    total_requests = requests_query.count()
    new_requests = requests_query.filter_by(status="New").count()
    in_progress = requests_query.filter_by(status="In Progress").count()
    completed = requests_query.filter_by(status="Completed").count()

    request_ids = [
        row[0]
        for row in requests_query.with_entities(ServiceRequest.id).all()
    ]

    total_paid = 0
    pending_payments = 0

    if request_ids:
        total_paid = db.session.query(
            db.func.coalesce(db.func.sum(Payment.amount), 0)
        ).filter(
            Payment.request_id.in_(request_ids),
            Payment.status == "Approved",
        ).scalar()

        pending_payments = Payment.query.filter(
            Payment.request_id.in_(request_ids),
            Payment.status == "Pending",
        ).count()

    recent_requests = requests_query.order_by(
        ServiceRequest.created_at.desc()
    ).limit(5).all()

    return render_template(
        "user_dashboard.html",
        total_requests=total_requests,
        new_requests=new_requests,
        in_progress=in_progress,
        completed=completed,
        total_paid=total_paid,
        pending_payments=pending_payments,
        recent_requests=recent_requests,
    )


@app.route("/my-requests")
@login_required
def my_requests():
    if is_manager():
        return redirect(url_for("requests_page"))

    requests_list = customer_requests_query(current_user).order_by(
        ServiceRequest.created_at.desc()
    ).all()

    return render_template(
        "my_requests.html",
        requests=requests_list,
    )


# =========================================================
# CUSTOMER: CREATE A NEW SERVICE REQUEST
# =========================================================


@app.route("/new-request", methods=["GET", "POST"])
@login_required
def new_request():
    if is_manager():
        return redirect(url_for("requests_page"))

    manager = User.query.filter(
        User.role.in_(["manager", "admin"]),
        User.is_active.is_(True)
    ).order_by(User.id.asc()).first()

    if not manager:
        flash("No service manager is currently available.", "error")
        return redirect(url_for("user_dashboard"))

    allowed_services = {
        "CV Writing & Design",
        "Cover Letter Writing",
        "Job Application Assistance",
        "Online Job Applications",
        "LinkedIn Profile Creation",
        "Interview Preparation",

        "Scholarship Applications",
        "University Applications",
        "International University Applications",
        "School Registration Assistance",
        "Personal Statement Writing",
        "Academic Document Formatting",

        "Business Registration Assistance",
        "Company Name Search Assistance",
        "Business Plan Writing",
        "Business Profile Creation",
        "TIN Registration Assistance",
        "Online Business Setup",

        "Logo Design",
        "Business Card Design",
        "Poster & Flyer Design",
        "Certificate Design",
        "Social Media Designs",
        "Company Branding",

        "Website Design",
        "Web Application Development",
        "E-commerce Website Development",
        "Domain & Hosting Assistance",
        "Website Maintenance",
        "Database & System Development",

        "Government Online Application Assistance",
        "Passport Application Assistance",
        "Visa Application Assistance",
        "Online Exam Registration",
        "Appointment Booking",
        "Account Creation & Verification Assistance",

        "Document Typing",
        "PDF Editing & Formatting",
        "Document Conversion",
        "Scanning & Digitalization",
        "Professional Letter Writing",
        "Translation Assistance",

        "Social Media Account Setup",
        "Facebook Page Creation",
        "Digital Marketing",
        "Google Business Profile Setup",
        "Online Advertising Assistance",
        "Social Media Management",

        "Other Digital Service"
    }

    if request.method == "POST":
        service_name = request.form.get(
            "service_name", ""
        ).strip()

        if service_name not in allowed_services:
            flash("Please select a valid service.", "error")
            return redirect(url_for("new_request"))

        title = request.form.get("title", "").strip()
        details = request.form.get("details", "").strip()
        priority = request.form.get("priority", "Normal").strip()

        customer_name = request.form.get(
            "customer_name", ""
        ).strip() or current_user.full_name or current_user.username

        phone = request.form.get(
            "phone", ""
        ).strip() or current_user.phone or ""

        email = request.form.get(
            "email", ""
        ).strip() or current_user.email or ""

        if not title or not details or not phone:
            flash(
                "Please provide the title, details and phone number.",
                "error"
            )
            return redirect(url_for("new_request"))

        if priority not in ["Normal", "Urgent", "High"]:
            priority = "Normal"

        new_service_request = ServiceRequest(
            owner_id=manager.id,
            customer_user_id=current_user.id,
            customer_name=customer_name,
            phone=phone,
            email=email,
            service_name=service_name,
            title=title,
            details=details,
            priority=priority,
            status="New",
            quoted_price=0,
            amount_paid=0
        )

        try:
            db.session.add(new_service_request)
            db.session.commit()

            flash(
                "Your service request was submitted successfully!",
                "success"
            )
            return redirect(url_for("my_requests"))

        except Exception:
            db.session.rollback()
            app.logger.exception("Service request submission failed.")
            flash(
                "Could not submit your request. Please try again.",
                "error"
            )
            return redirect(url_for("new_request"))

    return render_template("new_request.html")

# =========================================================
# CUSTOMER: PAY FOR A SERVICE REQUEST
# =========================================================

@app.route(
    "/requests/<int:request_id>/pay",
    methods=["GET", "POST"],
)
@login_required
def pay_for_request(request_id):
    if is_manager():
        return redirect(url_for("payments"))

    service_request = get_customer_request_or_404(request_id)

    if service_request.status == "Cancelled":
        flash("You cannot pay for a cancelled request.", "error")
        return redirect(url_for("my_requests"))

    balance = remaining_amount(service_request)

    if balance <= 0:
        flash("This request has already been fully paid.", "success")
        return redirect(url_for("my_payments"))

    if request.method == "POST":
        try:
            amount = float(request.form.get("amount", "0"))

            if amount <= 0:
                raise ValueError

            if amount > balance:
                flash(
                    f"Your payment cannot exceed the remaining balance "
                    f"of {balance:,.0f} RWF.",
                    "error",
                )
                return redirect(
                    url_for("pay_for_request", request_id=request_id)
                )

        except (TypeError, ValueError):
            flash("Enter a valid payment amount.", "error")
            return redirect(
                url_for("pay_for_request", request_id=request_id)
            )

        method = request.form.get("method", "").strip()

        if method not in PAYMENT_METHODS:
            flash("Choose MTN MoMo or Airtel Money.", "error")
            return redirect(
                url_for("pay_for_request", request_id=request_id)
            )

        reference = request.form.get("reference", "").strip()

        if not reference or len(reference) > 120:
            flash("Enter a valid transaction ID.", "error")
            return redirect(
                url_for("pay_for_request", request_id=request_id)
            )

        duplicate = Payment.query.filter(
            db.func.lower(Payment.reference) == reference.lower()
        ).first()

        if duplicate:
            flash(
                "This transaction ID has already been submitted.",
                "error",
            )
            return redirect(
                url_for("pay_for_request", request_id=request_id)
            )

        proof = request.files.get("proof")

        if not proof or not proof.filename:
            flash("Upload a screenshot of your payment.", "error")
            return redirect(
                url_for("pay_for_request", request_id=request_id)
            )

        proof_filename = save_payment_proof(proof)

        if not proof_filename:
            flash(
                "Invalid screenshot. Use PNG, JPG, JPEG or WEBP.",
                "error",
            )
            return redirect(
                url_for("pay_for_request", request_id=request_id)
            )

        payment = Payment(
            owner_id=service_request.owner_id,
            request_id=service_request.id,
            amount=amount,
            method=method,
            reference=reference,
            status="Pending",
            proof_filename=proof_filename,
        )

        try:
            db.session.add(payment)
            db.session.commit()

            flash(
                "Payment proof submitted. Your payment is awaiting "
                "manager verification.",
                "success",
            )

            return redirect(url_for("my_payments"))

        except Exception:
            db.session.rollback()

            try:
                os.remove(
                    os.path.join(
                        PAYMENT_PROOF_FOLDER,
                        proof_filename,
                    )
                )
            except OSError:
                pass

            app.logger.exception("Payment submission failed.")
            flash("Could not submit payment. Please try again.", "error")

    return render_template(
        "payment_form.html",
        service_request=service_request,
        balance=balance,
        payment_phone=app.config["PAYMENT_PHONE"],
        payment_recipient=app.config["PAYMENT_RECIPIENT"],
        payment_methods=PAYMENT_METHODS,
    )


# =========================================================
# CUSTOMER: MY PAYMENTS
# =========================================================

@app.route("/my-payments")
@login_required
def my_payments():
    if is_manager():
        return redirect(url_for("payments"))

    request_ids = [
        row[0]
        for row in customer_requests_query(
            current_user
        ).with_entities(ServiceRequest.id).all()
    ]

    payment_rows = []

    if request_ids:
        payment_rows = Payment.query.filter(
            Payment.request_id.in_(request_ids)
        ).order_by(
            Payment.created_at.desc()
        ).all()

    return render_template(
        "my_payments.html",
        payments=payment_rows,
    )


# =========================================================
# ADMIN: REQUESTS
# =========================================================

@app.route("/requests")
@login_required
@manager_required
def requests_page():
    status = request.args.get("status", "").strip()

    query = ServiceRequest.query.filter_by(
        owner_id=current_user.id
    )

    allowed_statuses = [
        "New", "In Progress", "Waiting for Customer",
        "Completed", "Cancelled",
    ]

    if status in allowed_statuses:
        query = query.filter_by(status=status)
    else:
        status = ""

    all_requests = query.order_by(
        ServiceRequest.created_at.desc()
    ).all()

    return render_template(
        "requests.html",
        requests=all_requests,
        selected_status=status,
    )


@app.route("/requests/<int:request_id>", methods=["GET", "POST"])
@login_required
@manager_required
def request_detail(request_id):
    service_request = get_request_or_404(request_id)

    if request.method == "POST":
        status = request.form.get("status", "New")

        allowed_statuses = [
            "New", "In Progress", "Waiting for Customer",
            "Completed", "Cancelled",
        ]

        if status not in allowed_statuses:
            flash("Invalid request status.", "error")
            return redirect(
                url_for("request_detail", request_id=request_id)
            )


        try:
            quoted_price = float(
                request.form.get("quoted_price", "0") or 0
            )

            if quoted_price < 0:
                raise ValueError

            if quoted_price < (service_request.amount_paid or 0):
                flash(
                    "Quoted price cannot be lower than the amount "
                    "already paid.",
                    "error",
                )
                return redirect(
                    url_for("request_detail", request_id=request_id)
                )

        except (TypeError, ValueError):
            flash("Enter a valid quoted price.", "error")
            return redirect(
                url_for("request_detail", request_id=request_id)
            )

        if status == "Completed":
            existing_results = ServiceResult.query.filter_by(
                request_id=service_request.id,
                owner_id=current_user.id
            ).count()

            if existing_results == 0:
                flash(
                    "Upload at least one completed result before marking "
                    "this request as Completed.",
                    "error"
                )
                return redirect(
                    url_for("request_detail", request_id=request_id)
                )

        service_request.status = status
        service_request.quoted_price = quoted_price
        service_request.staff_notes = request.form.get(
            "staff_notes", ""
        ).strip()

        db.session.commit()

        flash("Request updated successfully.", "success")

        return redirect(
            url_for("request_detail", request_id=request_id)
        )

      
    payments_list = Payment.query.filter_by(
        request_id=service_request.id
    ).order_by(Payment.created_at.desc()).all()

    results_list = ServiceResult.query.filter_by(
        request_id=service_request.id,
        owner_id=current_user.id
    ).order_by(ServiceResult.uploaded_at.desc()).all()

    return render_template(
        "request_detail.html",
        service_request=service_request,
        payments=payments_list,
        results=results_list,
    )


# MANAGER: UPLOAD COMPLETED SERVICE RESULTS
# =========================================================

@app.route(
    "/requests/<int:request_id>/upload-results",
    methods=["POST"]
)
@login_required
@manager_required
def upload_service_results(request_id):

    service_request = get_request_or_404(request_id)

    uploaded_files = request.files.getlist("result_files")

    uploaded_files = [
        file for file in uploaded_files
        if file and file.filename
    ]

    if not uploaded_files:
        flash("Please select at least one file.", "error")
        return redirect(
            url_for("request_detail", request_id=request_id)
        )

    if len(uploaded_files) > 10:
        flash("You can upload a maximum of 10 files at once.", "error")
        return redirect(
            url_for("request_detail", request_id=request_id)
        )

    # Validate all files before saving any of them.
    for file in uploaded_files:
        if not allowed_result_file(file.filename):
            flash(
                "Unsupported file type. Allowed: PDF, images, "
                "Word, Excel and TXT.",
                "error"
            )
            return redirect(
                url_for("request_detail", request_id=request_id)
            )

    description = request.form.get(
        "description", ""
    ).strip()[:2000]

    saved_files = []

    try:
        for file in uploaded_files:
            stored_name = save_service_result(file)

            if not stored_name:
                raise ValueError("A file could not be saved.")

            original_name = secure_filename(file.filename)

            result = ServiceResult(
                request_id=service_request.id,
                owner_id=current_user.id,
                customer_user_id=service_request.customer_user_id,
                original_filename=original_name,
                stored_filename=stored_name,
                description=description,
            )

            db.session.add(result)
            saved_files.append(stored_name)

        db.session.commit()

        flash(
            f"{len(saved_files)} result file(s) uploaded successfully.",
            "success"
        )

    except Exception:
        db.session.rollback()

        for filename in saved_files:
            try:
                os.remove(
                    os.path.join(
                        SERVICE_RESULTS_FOLDER,
                        filename
                    )
                )
            except OSError:
                pass

        app.logger.exception("Service result upload failed.")
        flash("Could not upload the result files.", "error")

    return redirect(
        url_for("request_detail", request_id=request_id)
    )


# =========================================================
# CUSTOMER: MY RESULTS
# =========================================================

@app.route("/my-results")
@login_required
def my_results():

    if is_manager():
        return redirect(url_for("requests_page"))

    results_list = ServiceResult.query.filter_by(
        customer_user_id=current_user.id
    ).order_by(
        ServiceResult.uploaded_at.desc()
    ).all()

    return render_template(
        "my_results.html",
        results=results_list
    )


# =========================================================
# CUSTOMER: SECURE RESULT DOWNLOAD
# =========================================================

@app.route("/my-results/<int:result_id>/download")
@login_required
def download_service_result(result_id):

    if is_manager():
        result = ServiceResult.query.filter_by(
            id=result_id,
            owner_id=current_user.id
        ).first_or_404()
    else:
        result = ServiceResult.query.filter_by(
            id=result_id,
            customer_user_id=current_user.id
        ).first_or_404()

    return send_from_directory(
        SERVICE_RESULTS_FOLDER,
        result.stored_filename,
        as_attachment=True,
        download_name=result.original_filename
    )# =========================================================
# ADMIN: CUSTOMERS
# =========================================================

@app.route("/customers")
@login_required
@manager_required
def customers():
    customer_rows = db.session.query(
        ServiceRequest.customer_name,
        ServiceRequest.phone,
        ServiceRequest.email,
        db.func.count(ServiceRequest.id).label("request_count"),
    ).filter(
        ServiceRequest.owner_id == current_user.id
    ).group_by(
        ServiceRequest.customer_name,
        ServiceRequest.phone,
        ServiceRequest.email,
    ).order_by(ServiceRequest.customer_name).all()

    return render_template("customers.html", customers=customer_rows)


# =========================================================
# ADMIN: SERVICES
# =========================================================

@app.route("/services", methods=["GET", "POST"])
@login_required
@manager_required
def services():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()

        try:
            price = float(request.form.get("price", "0") or 0)

            if price < 0:
                raise ValueError

        except (TypeError, ValueError):
            flash("Enter a valid price.", "error")
            return redirect(url_for("services"))

        if not name:
            flash("Service name is required.", "error")
            return redirect(url_for("services"))

        duplicate = Service.query.filter(
            db.func.lower(Service.name) == name.lower(),
            Service.owner_id == current_user.id,
        ).first()

        if duplicate:
            flash("This service already exists.", "error")
            return redirect(url_for("services"))

        db.session.add(
            Service(
                owner_id=current_user.id,
                name=name,
                description=description,
                price=price,
                is_active=True,
            )
        )

        db.session.commit()

        flash("Service added successfully.", "success")
        return redirect(url_for("services"))

    all_services = Service.query.filter_by(
        owner_id=current_user.id
    ).order_by(Service.name).all()

    return render_template("services.html", services=all_services)


# =========================================================
# ADMIN: PAYMENTS
# =========================================================

@app.route("/payments", methods=["GET", "POST"])
@login_required
@manager_required
def payments():
    if request.method == "POST":
        try:
            request_id = int(request.form.get("request_id", "0"))
            amount = float(request.form.get("amount", "0"))

            if amount <= 0:
                raise ValueError

        except (TypeError, ValueError):
            flash("Enter a valid request and payment amount.", "error")
            return redirect(url_for("payments"))

        service_request = ServiceRequest.query.filter_by(
            id=request_id,
            owner_id=current_user.id,
        ).first()

        if not service_request:
            flash("Service request not found.", "error")
            return redirect(url_for("payments"))

        method = request.form.get("method", "Cash").strip()

        if method not in [
            "Cash", "Mobile Money", "Bank Transfer", "Other"
        ]:
            method = "Other"

        payment = Payment(
            owner_id=current_user.id,
            request_id=request_id,
            amount=amount,
            method=method,
            reference=request.form.get("reference", "").strip(),
            status="Approved",
            verified_at=datetime.utcnow(),
            verified_by=current_user.id,
        )

        db.session.add(payment)

        service_request.amount_paid = (
            service_request.amount_paid or 0
        ) + amount

        db.session.commit()

        flash("Payment recorded successfully.", "success")
        return redirect(url_for("payments"))

    payment_rows = Payment.query.filter_by(
        owner_id=current_user.id
    ).order_by(
        Payment.created_at.desc()
    ).all()

    unpaid_requests = ServiceRequest.query.filter(
        ServiceRequest.owner_id == current_user.id,
        ServiceRequest.status != "Cancelled",
    ).order_by(
        ServiceRequest.created_at.desc()
    ).all()

    return render_template(
        "payments.html",
        payments=payment_rows,
        requests=unpaid_requests,
    )


# =========================================================
# ADMIN: APPROVE OR REJECT CUSTOMER PAYMENT
# =========================================================

@app.route(
    "/payments/<int:payment_id>/review",
    methods=["POST"],
)
@login_required
@manager_required
def review_payment(payment_id):
    payment = Payment.query.filter_by(
        id=payment_id,
        owner_id=current_user.id,
    ).first_or_404()

    if payment.status != "Pending":
        flash(
            "This payment has already been reviewed.",
            "error",
        )
        return redirect(url_for("payments"))

    action = request.form.get("action", "").strip().lower()

    if action == "approve":
        service_request = ServiceRequest.query.filter_by(
            id=payment.request_id,
            owner_id=current_user.id,
        ).first()

        if not service_request:
            abort(404)

        balance = remaining_amount(service_request)

        if payment.amount > balance:
            flash(
                "This payment is greater than the remaining balance. "
                "Review the request before approving it.",
                "error",
            )
            return redirect(url_for("payments"))

        payment.status = "Approved"
        payment.verified_at = datetime.utcnow()
        payment.verified_by = current_user.id
        payment.rejection_reason = ""

        service_request.amount_paid = (
            service_request.amount_paid or 0
        ) + payment.amount

        try:
            db.session.commit()
            flash("Payment approved successfully.", "success")

        except Exception:
            db.session.rollback()
            app.logger.exception("Payment approval failed.")
            flash("Could not approve this payment.", "error")

    elif action == "reject":
        reason = request.form.get(
            "rejection_reason", ""
        ).strip()

        payment.status = "Rejected"
        payment.verified_at = datetime.utcnow()
        payment.verified_by = current_user.id
        payment.rejection_reason = reason[:1000]

        try:
            db.session.commit()
            flash("Payment rejected.", "success")

        except Exception:
            db.session.rollback()
            app.logger.exception("Payment rejection failed.")
            flash("Could not reject this payment.", "error")

    else:
        flash("Invalid payment action.", "error")

    return redirect(url_for("payments"))


# =========================================================
# ADMIN: VIEW PAYMENT SCREENSHOT
# =========================================================

@app.route("/payment-proof/<int:payment_id>")
@login_required
@manager_required
def payment_proof(payment_id):
    payment = Payment.query.filter_by(
        id=payment_id,
        owner_id=current_user.id,
    ).first_or_404()

    if not payment.proof_filename:
        abort(404)

    return send_from_directory(
        PAYMENT_PROOF_FOLDER,
        payment.proof_filename,
    )


# =========================================================
# ADMIN: REPORTS
# =========================================================

@app.route("/reports")
@login_required
@manager_required
def reports():
    query = ServiceRequest.query.filter_by(
        owner_id=current_user.id
    )

    total_requests = query.count()
    completed = query.filter_by(status="Completed").count()

    total_quoted = db.session.query(
        db.func.coalesce(db.func.sum(ServiceRequest.quoted_price), 0)
    ).filter(
        ServiceRequest.owner_id == current_user.id
    ).scalar()

    total_paid = db.session.query(
        db.func.coalesce(db.func.sum(Payment.amount), 0)
    ).filter(
        Payment.owner_id == current_user.id,
        Payment.status == "Approved",
    ).scalar()

    return render_template(
        "reports.html",
        total_requests=total_requests,
        completed=completed,
        total_quoted=total_quoted,
        total_paid=total_paid,
    )


# =========================================================
# ADMIN: SETTINGS
# =========================================================

@app.route("/settings", methods=["GET", "POST"])
@login_required
@manager_required
def settings():
    if request.method == "POST":
        flash("Settings saved.", "success")
        return redirect(url_for("settings"))

    return render_template("settings.html")


# =========================================================
# USER MANAGEMENT
# =========================================================

@app.route("/user-management")
@login_required
@manager_required
def user_management():
    search = request.args.get("search", "").strip()
    selected_role = request.args.get("role", "").strip().lower()
    selected_status = request.args.get("status", "").strip().lower()

    query = User.query

    if search:
        pattern = f"%{search}%"

        query = query.filter(
            or_(
                User.username.ilike(pattern),
                User.full_name.ilike(pattern),
                User.email.ilike(pattern),
                User.phone.ilike(pattern),
            )
        )

    if selected_role in ("manager", "admin", "user"):
        query = query.filter_by(role=selected_role)

    if selected_status == "active":
        query = query.filter_by(is_active=True)
    elif selected_status == "inactive":
        query = query.filter_by(is_active=False)

    users = query.order_by(User.id.desc()).all()

    total_users = User.query.count()

    manager_count = User.query.filter(
        User.role.in_(["manager", "admin"])
    ).count()

    customer_count = User.query.filter_by(role="user").count()
    active_count = User.query.filter_by(is_active=True).count()
    inactive_count = User.query.filter_by(is_active=False).count()

    return render_template(
        "user_management.html",
        users=users,
        total_users=total_users,
        manager_count=manager_count,
        customer_count=customer_count,
        active_count=active_count,
        inactive_count=inactive_count,
        search=search,
        selected_role=selected_role,
        selected_status=selected_status,
    )


@app.route("/user-management/<int:user_id>")
@login_required
@manager_required
def user_details(user_id):
    managed_user = db.get_or_404(User, user_id)

    request_count = ServiceRequest.query.filter(
        or_(
            ServiceRequest.customer_user_id == managed_user.id,
            ServiceRequest.owner_id == managed_user.id,
        )
    ).count()

    service_count = Service.query.filter_by(
        owner_id=managed_user.id
    ).count()

    payment_count = Payment.query.filter_by(
        owner_id=managed_user.id
    ).count()

    return render_template(
        "user_details.html",
        managed_user=managed_user,
        request_count=request_count,
        service_count=service_count,
        payment_count=payment_count,
    )


@app.route(
    "/user-management/<int:user_id>/toggle-status",
    methods=["POST"],
)
@login_required
@manager_required
def toggle_user_status(user_id):
    managed_user = db.get_or_404(User, user_id)

    if managed_user.role in ("manager", "admin"):
        flash(
            "Manager and admin accounts cannot be deactivated here.",
            "error",
        )
        return redirect(url_for("user_management"))

    if managed_user.id == current_user.id:
        flash("You cannot deactivate your own account.", "error")
        return redirect(url_for("user_management"))

    managed_user.is_active = not managed_user.is_active

    try:
        db.session.commit()

        if managed_user.is_active:
            flash(
                f"Account for {managed_user.full_name or managed_user.username} "
                "has been activated.",
                "success",
            )
        else:
            flash(
                f"Account for {managed_user.full_name or managed_user.username} "
                "has been deactivated.",
                "success",
            )

    except Exception:
        db.session.rollback()
        app.logger.exception("Could not update account status.")
        flash("Could not update this account. Please try again.", "error")

    return redirect(url_for("user_management"))


@app.route(
    "/user-management/<int:user_id>/delete",
    methods=["POST"],
)
@login_required
@manager_required
def delete_user_account(user_id):
    managed_user = db.get_or_404(User, user_id)

    if managed_user.role in ("manager", "admin"):
        flash(
            "Manager and admin accounts cannot be deleted here.",
            "error",
        )
        return redirect(url_for("user_management"))

    if managed_user.id == current_user.id:
        flash("You cannot delete your own account.", "error")
        return redirect(url_for("user_management"))

    deleted_name = managed_user.full_name or managed_user.username

    try:
        Service.query.filter_by(
            owner_id=managed_user.id
        ).update(
            {Service.owner_id: None},
            synchronize_session=False,
        )

        ServiceRequest.query.filter_by(
            owner_id=managed_user.id
        ).update(
            {ServiceRequest.owner_id: None},
            synchronize_session=False,
        )

        ServiceRequest.query.filter_by(
            customer_user_id=managed_user.id
        ).update(
            {ServiceRequest.customer_user_id: None},
            synchronize_session=False,
        )

        Payment.query.filter_by(
            owner_id=managed_user.id
        ).update(
            {Payment.owner_id: None},
            synchronize_session=False,
        )

        Payment.query.filter_by(
            verified_by=managed_user.id
        ).update(
            {Payment.verified_by: None},
            synchronize_session=False,
        )

        db.session.delete(managed_user)
        db.session.commit()

        flash(
            f"Account for {deleted_name} has been deleted. "
            "Related service requests and payment records were preserved.",
            "success",
        )

    except Exception:
        db.session.rollback()
        app.logger.exception("Failed to delete user account.")
        flash(
            "Could not delete this account. Please try again.",
            "error",
        )

    return redirect(url_for("user_management"))

# =========================================================
# JOB CONNECT - ROUTES
# =========================================================

@app.route("/job-connect")
def job_connect():
    search = (request.args.get("search") or "").strip()
    category = (request.args.get("category") or "").strip()
    location = (request.args.get("location") or "").strip()

    jobs_query = JobListing.query.filter_by(status="Open")

    if search:
        jobs_query = jobs_query.filter(
            or_(
                JobListing.title.ilike(f"%{search}%"),
                JobListing.company_name.ilike(f"%{search}%"),
                JobListing.description.ilike(f"%{search}%"),
            )
        )

    if category:
        jobs_query = jobs_query.filter(
            JobListing.category.ilike(f"%{category}%")
        )

    if location:
        jobs_query = jobs_query.filter(
            JobListing.location.ilike(f"%{location}%")
        )

    jobs = jobs_query.order_by(
        JobListing.created_at.desc()
    ).all()

    return render_template(
        "job_connect.html",
        jobs=jobs,
        search=search,
        category=category,
        location=location,
    )


@app.route("/job-connect/jobs/<int:job_id>")
def job_details(job_id):
    job = db.get_or_404(JobListing, job_id)

    already_applied = False

    if current_user.is_authenticated:
        already_applied = JobApplication.query.filter_by(
            job_id=job.id,
            applicant_id=current_user.id,
        ).first() is not None

    return render_template(
        "job_details.html",
        job=job,
        already_applied=already_applied,
    )


@app.route("/job-connect/profile", methods=["GET", "POST"])
@login_required
def job_seeker_profile():
    profile = JobSeekerProfile.query.filter_by(
        user_id=current_user.id
    ).first()

    if request.method == "POST":
        if not profile:
            profile = JobSeekerProfile(user_id=current_user.id)
            db.session.add(profile)

        selected_skills = request.form.getlist("skills")

        profile.professional_title = (
            request.form.get("professional_title") or ""
        ).strip()

        profile.bio = (
            request.form.get("bio") or ""
        ).strip()

        profile.skills = ", ".join(selected_skills)

        profile.education = (
            request.form.get("education") or ""
        ).strip()

        profile.experience = (
            request.form.get("experience") or ""
        ).strip()

        profile.preferred_location = (
            request.form.get("preferred_location") or ""
        ).strip()

        try:
            db.session.commit()
            flash("Your Job Seeker Profile was saved successfully.", "success")
            return redirect(url_for("job_seeker_profile"))

        except Exception:
            db.session.rollback()
            app.logger.exception("Could not save Job Seeker profile.")
            flash("Could not save your profile. Please try again.", "error")

    return render_template(
        "job_seeker_profile.html",
        profile=profile,
        selected_skills=(
            profile.skills.split(", ") if profile and profile.skills else []
        )
    )

@app.route("/opportunities/job-seekers")
@login_required
def opportunities_seekers():
    # Only employers with a company profile and managers can search.
    if not is_manager():
        employer = EmployerProfile.query.filter_by(
            user_id=current_user.id
        ).first()

        if not employer:
            flash(
                "Please create your Employer Profile before searching for candidates.",
                "error"
            )
            return redirect(url_for("employer_profile"))

    search = (request.args.get("q") or "").strip()

    candidates_query = JobSeekerProfile.query.join(
        User,
        JobSeekerProfile.user_id == User.id
    ).filter(
        User.is_active.is_(True),
        JobSeekerProfile.professional_title.isnot(None),
        JobSeekerProfile.professional_title != ""
    )

    if search:
        pattern = f"%{search}%"

        candidates_query = candidates_query.filter(
            or_(
                JobSeekerProfile.professional_title.ilike(pattern),
                JobSeekerProfile.skills.ilike(pattern),
                JobSeekerProfile.education.ilike(pattern),
                JobSeekerProfile.preferred_location.ilike(pattern)
            )
        )

    candidates = candidates_query.order_by(
        JobSeekerProfile.updated_at.desc()
    ).all()

    return render_template(
        "opportunities_seekers.html",
        candidates=candidates,
        search=search
    )


@app.route("/job-connect/employer/profile", methods=["GET", "POST"])
@login_required
def employer_profile():
    profile = EmployerProfile.query.filter_by(
        user_id=current_user.id
    ).first()

    if request.method == "POST":
        company_name = (
            request.form.get("company_name") or ""
        ).strip()

        if not company_name:
            flash("Company name is required.", "error")
            return render_template(
                "employer_profile.html",
                profile=profile,
            )

        if not profile:
            profile = EmployerProfile(user_id=current_user.id)
            db.session.add(profile)

        profile.company_name = company_name
        profile.company_description = (
            request.form.get("company_description") or ""
        ).strip()
        profile.industry = (
            request.form.get("industry") or ""
        ).strip()
        profile.website = (
            request.form.get("website") or ""
        ).strip()
        profile.contact_phone = (
            request.form.get("contact_phone") or ""
        ).strip()
        profile.whatsapp_public = (
    (request.form.get("whatsapp_public") or "").strip().lower()
    in ("on", "true", "1", "yes")
)

        try:
            db.session.commit()
            flash("Employer profile saved successfully.", "success")
            return redirect(url_for("employer_profile"))

        except Exception:
            db.session.rollback()
            app.logger.exception("Could not save Employer profile.")
            flash("Could not save your company profile.", "error")

    return render_template(
        "employer_profile.html",
        profile=profile,
    )


@app.route("/job-connect/employer/jobs/new", methods=["GET", "POST"])
@login_required
def create_job():
    employer = EmployerProfile.query.filter_by(
        user_id=current_user.id
    ).first()

    if not employer:
        flash("Create your Employer profile before publishing a job.", "warning")
        return redirect(url_for("employer_profile"))

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        category = (request.form.get("category") or "").strip()
        location = (request.form.get("location") or "").strip()
        employment_type = (
            request.form.get("employment_type") or ""
        ).strip()
        salary = (request.form.get("salary") or "").strip()
        description = (
            request.form.get("description") or ""
        ).strip()
        requirements = (
            request.form.get("requirements") or ""
        ).strip()

        if not all([title, category, location, employment_type, description]):
            flash("Please complete all required job fields.", "error")
            return render_template("create_job.html", employer=employer)

        job = JobListing(
            employer_id=current_user.id,
            title=title,
            company_name=employer.company_name,
            category=category,
            location=location,
            employment_type=employment_type,
            salary=salary,
            description=description,
            requirements=requirements,
            status="Open",
        )

        try:
            db.session.add(job)
            db.session.commit()
            flash("Your job vacancy has been published.", "success")
            return redirect(url_for("my_jobs"))

        except Exception:
            db.session.rollback()
            app.logger.exception("Could not publish job vacancy.")
            flash("Could not publish this job. Please try again.", "error")

    return render_template(
        "create_job.html",
        employer=employer,
    )


@app.route("/job-connect/employer/jobs")
@login_required
def my_jobs():
    jobs = JobListing.query.filter_by(
        employer_id=current_user.id
    ).order_by(
        JobListing.created_at.desc()
    ).all()

    return render_template(
        "my_jobs.html",
        jobs=jobs,
    )


@app.route(
    "/job-connect/jobs/<int:job_id>/apply",
    methods=["POST"],
)
@login_required
def apply_for_job(job_id):
    job = db.get_or_404(JobListing, job_id)

    if job.employer_id == current_user.id:
        flash("You cannot apply for your own job vacancy.", "error")
        return redirect(url_for("job_details", job_id=job.id))

    if job.status != "Open":
        flash("This job is no longer accepting applications.", "warning")
        return redirect(url_for("job_details", job_id=job.id))

    seeker_profile = JobSeekerProfile.query.filter_by(
        user_id=current_user.id
    ).first()

    if not seeker_profile:
        flash("Complete your Job Seeker profile before applying.", "warning")
        return redirect(url_for("job_seeker_profile"))

    existing_application = JobApplication.query.filter_by(
        job_id=job.id,
        applicant_id=current_user.id,
    ).first()

    if existing_application:
        flash("You have already applied for this job.", "info")
        return redirect(url_for("job_details", job_id=job.id))

    application = JobApplication(
        job_id=job.id,
        applicant_id=current_user.id,
        cover_letter=(
            request.form.get("cover_letter") or ""
        ).strip(),
        status="Submitted",
    )

    try:
        db.session.add(application)
        db.session.commit()
        flash("Your job application has been submitted.", "success")

    except Exception:
        db.session.rollback()
        app.logger.exception("Could not submit job application.")
        flash("Could not submit your application. Please try again.", "error")

    return redirect(url_for("my_applications"))


@app.route("/job-connect/my-applications")
@login_required
def my_applications():
    applications = JobApplication.query.filter_by(
        applicant_id=current_user.id
    ).order_by(
        JobApplication.created_at.desc()
    ).all()

    return render_template(
        "my_applications.html",
        applications=applications,
    )


@app.route("/job-connect/employer/jobs/<int:job_id>/applications")
@login_required
def job_applications(job_id):
    job = db.get_or_404(JobListing, job_id)

    if job.employer_id != current_user.id:
        abort(403)

    applications = JobApplication.query.filter_by(
        job_id=job.id
    ).order_by(
        JobApplication.created_at.desc()
    ).all()

    return render_template(
        "employer_applications.html",
        job=job,
        applications=applications,
    )


@app.route(
    "/job-connect/applications/<int:application_id>/status",
    methods=["POST"],
)
@login_required
def update_job_application_status(application_id):
    application = db.get_or_404(JobApplication, application_id)
    job = db.get_or_404(JobListing, application.job_id)

    if job.employer_id != current_user.id:
        abort(403)

    allowed_statuses = [
        "Submitted",
        "Reviewing",
        "Shortlisted",
        "Rejected",
        "Accepted",
    ]

    new_status = (request.form.get("status") or "").strip()

    if new_status not in allowed_statuses:
        abort(400)

    application.status = new_status

    try:
        db.session.commit()
        flash("Application status updated.", "success")

    except Exception:
        db.session.rollback()
        app.logger.exception("Could not update application status.")
        flash("Could not update application status.", "error")

    return redirect(
        url_for("job_applications", job_id=job.id)
    )


# =========================================================
# INITIAL DATABASE SETUP
# =========================================================

with app.app_context():
    db.create_all()
    migrate_database()

    if User.query.count() == 0:
        initial_username = os.getenv("ADMIN_USERNAME", "manager")
        initial_password = os.getenv("ADMIN_PASSWORD")

        if not initial_password:
            initial_password = os.urandom(18).hex()

            print("\nINITIAL MANAGER ACCOUNT")
            print("Username:", initial_username)
            print("Temporary password:", initial_password)
            print("Save this password securely.\n")

        admin_email = normalized_email(
            os.getenv("ADMIN_EMAIL", "")
        ) or None

        manager = User(
            username=initial_username,
            email=admin_email,
            full_name=os.getenv(
                "ADMIN_FULL_NAME",
                "Pacifique Digital Services Manager",
            ),
            role="manager",
            is_active=True,
        )

        manager.set_password(initial_password)
        db.session.add(manager)
        db.session.commit()


# =========================================================
# RUN APPLICATION
# =========================================================

if __name__ == "__main__":
    app.run(
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true"
    )
