from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from datetime import datetime
import os

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///ise_finance.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "change_this_secret_key"

db = SQLAlchemy(app)

# IMPORTANT : créer les tables dès que l'app est chargée (utile pour Render/gunicorn)
with app.app_context():
    db.create_all()


# ---------- MODELS ----------

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    matricule = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    classe = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(30))

    contributions = db.relationship("Contribution", backref="student", lazy=True)

    def total_contributions(self):
        return sum(c.amount for c in self.contributions)


class Contribution(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    description = db.Column(db.String(200), default="Cotisation hebdomadaire")


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    target_budget = db.Column(db.Float)  # budget prévu

    transactions = db.relationship("EventTransaction", backref="event", lazy=True)

    @property
    def total_revenue(self):
        return sum(t.amount for t in self.transactions if t.type == "revenue")

    @property
    def total_donation(self):
        return sum(t.amount for t in self.transactions if t.type == "donation")

    @property
    def total_expense(self):
        return sum(t.amount for t in self.transactions if t.type == "expense")

    @property
    def balance(self):
        return self.total_revenue + self.total_donation - self.total_expense


class EventTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # revenue, donation, expense
    label = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    person = db.Column(db.String(120))  # personne qui a payé / reçu


# ---------- ROUTES ----------

@app.route("/")
def dashboard():
    total_contrib = db.session.query(
        func.coalesce(func.sum(Contribution.amount), 0)
    ).scalar()
    nb_students = Student.query.count()
    nb_events = Event.query.count()

    events = Event.query.order_by(Event.start_date.desc().nullslast()).all()
    recent_contribs = Contribution.query.order_by(
        Contribution.date.desc()
    ).limit(5).all()

    return render_template(
        "dashboard.html",
        total_contrib=total_contrib or 0,
        nb_students=nb_students,
        nb_events=nb_events,
        events=events,
        recent_contribs=recent_contribs,
    )


# ---- Students ----

@app.route("/students")
def students_list():
    students = Student.query.order_by(Student.classe, Student.name).all()
    return render_template("students.html", students=students)


@app.route("/students/new", methods=["GET", "POST"])
def students_new():
    if request.method == "POST":
        matricule = request.form.get("matricule")
        name = request.form.get("name")
        classe = request.form.get("classe")
        phone = request.form.get("phone")

        if not matricule or not name or not classe:
            flash("Matricule, nom et classe sont obligatoires.", "danger")
            return redirect(url_for("students_new"))

        if Student.query.filter_by(matricule=matricule).first():
            flash("Ce matricule existe déjà.", "danger")
            return redirect(url_for("students_new"))

        s = Student(matricule=matricule, name=name, classe=classe, phone=phone)
        db.session.add(s)
        db.session.commit()
        flash("Étudiant ajouté avec succès.", "success")
        return redirect(url_for("students_list"))
    return render_template("student_form.html")


# ---- Contributions ----

@app.route("/contributions")
def contributions_list():
    contribs = (
        Contribution.query.join(Student)
        .add_columns(
            Contribution.id,
            Contribution.amount,
            Contribution.date,
            Contribution.description,
            Student.name,
            Student.classe,
        )
        .order_by(Contribution.date.desc())
        .all()
    )
    total_contrib = db.session.query(
        func.coalesce(func.sum(Contribution.amount), 0)
    ).scalar()
    return render_template(
        "contributions.html",
        contribs=contribs,
        total_contrib=total_contrib or 0,
    )


@app.route("/contributions/new", methods=["GET", "POST"])
def contributions_new():
    students = Student.query.order_by(Student.classe, Student.name).all()
    if request.method == "POST":
        student_id = request.form.get("student_id")
        amount = request.form.get("amount")
        description = request.form.get("description") or "Cotisation hebdomadaire"
        date_str = request.form.get("date")

        try:
            amount = float(amount)
        except (TypeError, ValueError):
            flash("Montant invalide.", "danger")
            return redirect(url_for("contributions_new"))

        if date_str:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            date_obj = datetime.utcnow().date()

        c = Contribution(
            student_id=student_id,
            amount=amount,
            description=description,
            date=date_obj,
        )
        db.session.add(c)
        db.session.commit()
        flash("Cotisation enregistrée.", "success")
        return redirect(url_for("contributions_list"))
    return render_t_
