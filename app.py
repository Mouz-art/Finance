from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    Response,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from datetime import datetime
import os

from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///ise_finance.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "change_this_secret_key"

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"


# ========= MODELES TECHNIQUES (CONFIG + UTILISATEURS) =========

class Config(db.Model):
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(200), nullable=False)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    role = db.Column(db.String(50), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


# ========= MODELES METIER =========

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
    exercise = db.Column(db.String(20), nullable=False, default="2024-2025")


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    target_budget = db.Column(db.Float)
    exercise = db.Column(db.String(20), nullable=False, default="2024-2025")

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
    person = db.Column(db.String(120))


# ========= FONCTIONS UTILITAIRES =========

def get_current_exercise() -> str:
    cfg = Config.query.get("current_exercise")
    if cfg is None:
        cfg = Config(key="current_exercise", value="2024-2025")
        db.session.add(cfg)
        db.session.commit()
    return cfg.value


@app.context_processor
def inject_globals():
    return {
        "current_exercise": get_current_exercise(),
        "current_user": current_user,
    }


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ========= INIT DB + COMPTES PAR DEFAUT =========

with app.app_context():
    db.create_all()

    # Exercice courant par défaut
    if Config.query.get("current_exercise") is None:
        db.session.add(Config(key="current_exercise", value="2024-2025"))
        db.session.commit()

    # Création des comptes initiaux si aucun utilisateur
    if User.query.count() == 0:
        defaults = [
            ("tg", "TG", "tg123"),
            ("tga", "TGA", "tga123"),
            ("president", "PRESIDENT", "pres123"),
            ("vp", "VP", "vp123"),
        ]
        for username, role, pwd in defaults:
            u = User(username=username, role=role)
            u.set_password(pwd)
            db.session.add(u)
        db.session.commit()


# ========= ROUTES AUTH =========

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash("Connexion réussie.", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Nom d'utilisateur ou mot de passe incorrect.", "danger")
            return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Vous avez été déconnecté.", "info")
    return redirect(url_for("login"))


# ========= ROUTE : NOUVEL EXERCICE =========

@app.route("/exercise/new", methods=["GET", "POST"])
@login_required
def new_exercise():
    if request.method == "POST":
        name = request.form.get("name")
        if not name:
            flash("Le nom de l'exercice est obligatoire.", "danger")
            return redirect(url_for("new_exercise"))

        cfg = Config.query.get("current_exercise")
        if cfg is None:
            cfg = Config(key="current_exercise", value=name)
            db.session.add(cfg)
        else:
            cfg.value = name
        db.session.commit()

        flash(f"Nouvel exercice courant défini : {name}", "success")
        return redirect(url_for("dashboard"))

    return render_template("exercise_form.html")


# ========= ROUTE : EXPORT COTISATIONS =========

@app.route("/export/contributions")
@login_required
def export_contributions():
    exercise = get_current_exercise()
    contribs = (
        Contribution.query.filter_by(exercise=exercise)
        .order_by(Contribution.date.asc())
        .all()
    )

    lines = ["Matricule;Nom;Classe;Montant;Date;Description"]
    for c in contribs:
        lines.append(
            f"{c.student.matricule};"
            f"{c.student.name};"
            f"{c.student.classe};"
            f"{c.amount:.0f};"
            f"{c.date.strftime('%Y-%m-%d')};"
            f"{c.description}"
        )

    csv_data = "\n".join(lines)
    filename = f"cotisations_{exercise.replace(' ', '_')}.csv"

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"},
    )


# ========= ROUTES METIER =========

@app.route("/")
@login_required
def dashboard():
    exercise = get_current_exercise()

    total_contrib = (
        db.session.query(func.coalesce(func.sum(Contribution.amount), 0))
        .filter(Contribution.exercise == exercise)
        .scalar()
    )
    nb_students = Student.query.count()
    nb_events = Event.query.filter_by(exercise=exercise).count()

    events = (
        Event.query.filter_by(exercise=exercise)
        .order_by(Event.start_date.desc().nullslast())
        .all()
    )

    recent_contribs = (
        Contribution.query.filter_by(exercise=exercise)
        .order_by(Contribution.date.desc())
        .limit(5)
        .all()
    )

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
@login_required
def students_list():
    students = Student.query.order_by(Student.classe, Student.name).all()
    return render_template("students.html", students=students)


@app.route("/students/new", methods=["GET", "POST"])
@login_required
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
@login_required
def contributions_list():
    exercise = get_current_exercise()
    contribs = (
        Contribution.query.join(Student)
        .filter(Contribution.exercise == exercise)
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
    total_contrib = (
        db.session.query(func.coalesce(func.sum(Contribution.amount), 0))
        .filter(Contribution.exercise == exercise)
        .scalar()
    )
    return render_template(
        "contributions.html",
        contribs=contribs,
        total_contrib=total_contrib or 0,
    )


@app.route("/contributions/new", methods=["GET", "POST"])
@login_required
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

        exercise = get_current_exercise()

        c = Contribution(
            student_id=student_id,
            amount=amount,
            description=description,
            date=date_obj,
            exercise=exercise,
        )
        db.session.add(c)
        db.session.commit()
        flash("Cotisation enregistrée.", "success")
        return redirect(url_for("contributions_list"))
    return render_template("contribution_form.html", students=students)


# ---- Events ----

@app.route("/events")
@login_required
def events_list():
    exercise = get_current_exercise()
    events = (
        Event.query.filter_by(exercise=exercise)
        .order_by(Event.start_date.desc().nullslast())
        .all()
    )
    return render_template("events.html", events=events)


@app.route("/events/new", methods=["GET", "POST"])
@login_required
def events_new():
    if request.method == "POST":
        name = request.form.get("name")
        description = request.form.get("description")
        start_date_str = request.form.get("start_date")
        end_date_str = request.form.get("end_date")
        target_budget = request.form.get("target_budget")

        if not name:
            flash("Le nom de l'évènement est obligatoire.", "danger")
            return redirect(url_for("events_new"))

        start_date = (
            datetime.strptime(start_date_str, "%Y-%m-%d").date()
            if start_date_str
            else None
        )
        end_date = (
            datetime.strptime(end_date_str, "%Y-%m-%d").date()
            if end_date_str
            else None
        )
        target_budget = float(target_budget) if target_budget else None

        exercise = get_current_exercise()

        e = Event(
            name=name,
            description=description,
            start_date=start_date,
            end_date=end_date,
            target_budget=target_budget,
            exercise=exercise,
        )
        db.session.add(e)
        db.session.commit()
        flash("Évènement créé.", "success")
        return redirect(url_for("events_list"))
    return render_template("event_form.html")


@app.route("/events/<int:event_id>")
@login_required
def event_detail(event_id):
    event = Event.query.get_or_404(event_id)
    transactions = (
        EventTransaction.query.filter_by(event_id=event_id)
        .order_by(EventTransaction.date.desc())
        .all()
    )
    return render_template("event_detail.html", event=event, transactions=transactions)


@app.route("/events/<int:event_id>/transactions/new", methods=["GET", "POST"])
@login_required
def event_transaction_new(event_id):
    event = Event.query.get_or_404(event_id)
    if request.method == "POST":
        ttype = request.form.get("type")
        label = request.form.get("label")
        amount = request.form.get("amount")
        date_str = request.form.get("date")
        person = request.form.get("person")

        try:
            amount = float(amount)
        except (TypeError, ValueError):
            flash("Montant invalide.", "danger")
            return redirect(url_for("event_transaction_new", event_id=event_id))

        if not label or not ttype:
            flash("Type et libellé obligatoires.", "danger")
            return redirect(url_for("event_transaction_new", event_id=event_id))

        if date_str:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            date_obj = datetime.utcnow().date()

        t = EventTransaction(
            event_id=event_id,
            type=ttype,
            label=label,
            amount=amount,
            date=date_obj,
            person=person,
        )
        db.session.add(t)
        db.session.commit()
        flash("Transaction enregistrée.", "success")
        return redirect(url_for("event_detail", event_id=event_id))

    return render_template("event_transaction_form.html", event=event)


# ========= MAIN =========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
