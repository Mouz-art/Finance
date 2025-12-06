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
from functools import wraps

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
    role = db.Column(db.String(50), nullable=False)  # ex : TG, TGA, PRESIDENT, etc.
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


# ========= MODELE EXERCICE =========

class Exercise(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    contributions = db.relationship("Contribution", backref="exercise", lazy=True)
    events = db.relationship("Event", backref="exercise", lazy=True)


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
    exercise_id = db.Column(db.Integer, db.ForeignKey("exercise.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    description = db.Column(db.String(200), default="Cotisation hebdomadaire")


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    target_budget = db.Column(db.Float)
    exercise_id = db.Column(db.Integer, db.ForeignKey("exercise.id"), nullable=False)

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


# ========= HELPERS =========

def get_current_exercise():
    cfg = Config.query.get("current_exercise_id")
    if cfg is None or not cfg.value:
        return None
    try:
        ex_id = int(cfg.value)
        return Exercise.query.get(ex_id)
    except ValueError:
        return None


def set_current_exercise(exercise_id: int):
    cfg = Config.query.get("current_exercise_id")
    if cfg is None:
        cfg = Config(key="current_exercise_id", value=str(exercise_id))
        db.session.add(cfg)
    else:
        cfg.value = str(exercise_id)
    db.session.commit()


@app.context_processor
def inject_globals():
    return {
        "current_exercise": get_current_exercise(),
        "current_user": current_user,
    }


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def tg_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "TG":
            flash("Action réservée au Trésorier Général (TG).", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return wrapper


# ========= INIT DB =========

with app.app_context():
    db.create_all()
    # On ne crée plus d'utilisateur automatiquement
    # On ne crée pas d'exercice automatiquement non plus


# ========= CREATION DU PREMIER ADMIN (TG) =========

@app.route("/create-admin", methods=["GET", "POST"])
def create_admin():
    # Si un utilisateur existe déjà, on bloque l'accès
    if User.query.count() > 0:
        flash("Un utilisateur existe déjà. Veuillez vous connecter.", "warning")
        return redirect(url_for("login"))

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if not username or not password:
            flash("Tous les champs sont obligatoires.", "danger")
            return redirect(url_for("create_admin"))

        admin = User(username=username, role="TG")  # le premier est TG
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()

        flash("Trésorier Général créé avec succès. Vous pouvez vous connecter.", "success")
        return redirect(url_for("login"))

    return render_template("create_admin.html")


# ========= AUTH =========

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


# ========= GESTION DES EXERCICES =========

@app.route("/exercises", methods=["GET"])
@login_required
def exercises_list():
    exercises = Exercise.query.order_by(Exercise.created_at.desc()).all()
    current_ex = get_current_exercise()
    return render_template("exercises.html", exercises=exercises, current_exercise=current_ex)


@app.route("/exercises/select", methods=["POST"])
@login_required
def exercises_select():
    ex_id = request.form.get("exercise_id")
    if not ex_id:
        flash("Veuillez sélectionner un exercice.", "danger")
        return redirect(url_for("exercises_list"))

    ex = Exercise.query.get(ex_id)
    if not ex:
        flash("Exercice introuvable.", "danger")
        return redirect(url_for("exercises_list"))

    set_current_exercise(ex.id)
    flash(f"Exercice courant : {ex.name}", "success")
    return redirect(url_for("dashboard"))


@app.route("/exercises/new", methods=["GET", "POST"])
@login_required
@tg_required
def exercises_new():
    if request.method == "POST":
        name = request.form.get("name")
        if not name:
            flash("Le nom de l'exercice est obligatoire.", "danger")
            return redirect(url_for("exercises_new"))

        if Exercise.query.filter_by(name=name).first():
            flash("Un exercice avec ce nom existe déjà.", "danger")
            return redirect(url_for("exercises_new"))

        ex = Exercise(name=name)
        db.session.add(ex)
        db.session.commit()

        # on le met directement comme exercice courant
        set_current_exercise(ex.id)

        flash(f"Exercice {name} créé et sélectionné.", "success")
        return redirect(url_for("exercises_list"))

    return render_template("exercise_form.html", exercise=None)


@app.route("/exercises/<int:exercise_id>/edit", methods=["GET", "POST"])
@login_required
@tg_required
def exercises_edit(exercise_id):
    ex = Exercise.query.get_or_404(exercise_id)

    if request.method == "POST":
        name = request.form.get("name")
        if not name:
            flash("Le nom de l'exercice est obligatoire.", "danger")
            return redirect(url_for("exercises_edit", exercise_id=exercise_id))

        other = Exercise.query.filter(Exercise.name == name, Exercise.id != exercise_id).first()
        if other:
            flash("Un autre exercice porte déjà ce nom.", "danger")
            return redirect(url_for("exercises_edit", exercise_id=exercise_id))

        ex.name = name
        db.session.commit()

        flash("Exercice modifié avec succès.", "success")
        return redirect(url_for("exercises_list"))

    return render_template("exercise_form.html", exercise=ex)


@app.route("/exercises/<int:exercise_id>/delete", methods=["POST"])
@login_required
@tg_required
def exercises_delete(exercise_id):
    ex = Exercise.query.get_or_404(exercise_id)

    # On évite de supprimer un exercice qui a déjà des données
    has_contribs = Contribution.query.filter_by(exercise_id=exercise_id).count() > 0
    has_events = Event.query.filter_by(exercise_id=exercise_id).count() > 0

    if has_contribs or has_events:
        flash("Impossible de supprimer un exercice qui contient déjà des cotisations ou des évènements.", "danger")
        return redirect(url_for("exercises_list"))

    # si c'est l'exercice courant, on le désélectionne
    current_ex = get_current_exercise()
    if current_ex and current_ex.id == exercise_id:
        cfg = Config.query.get("current_exercise_id")
        if cfg:
            cfg.value = ""
            db.session.commit()

    db.session.delete(ex)
    db.session.commit()
    flash("Exercice supprimé avec succès.", "success")
    return redirect(url_for("exercises_list"))


# ========= EXPORT COTISATIONS =========

@app.route("/export/contributions")
@login_required
def export_contributions():
    exercise = get_current_exercise()
    if not exercise:
        flash("Veuillez d'abord choisir un exercice.", "warning")
        return redirect(url_for("exercises_list"))

    contribs = (
        Contribution.query.filter_by(exercise_id=exercise.id)
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
    filename = f"cotisations_{exercise.name.replace(' ', '_')}.csv"

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
    if not exercise:
        flash("Veuillez d'abord créer ou sélectionner un exercice.", "info")
        return redirect(url_for("exercises_list"))

    total_contrib = (
        db.session.query(func.coalesce(func.sum(Contribution.amount), 0))
        .filter(Contribution.exercise_id == exercise.id)
        .scalar()
    )
    nb_students = Student.query.count()
    nb_events = Event.query.filter_by(exercise_id=exercise.id).count()

    events = (
        Event.query.filter_by(exercise_id=exercise.id)
        .order_by(Event.start_date.desc().nullslast())
        .all()
    )

    recent_contribs = (
        Contribution.query.filter_by(exercise_id=exercise.id)
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
    exercise = get_current_exercise()
    if not exercise:
        flash("Veuillez d'abord créer ou sélectionner un exercice.", "info")
        return redirect(url_for("exercises_list"))

    students = Student.query.order_by(Student.classe, Student.name).all()
    return render_template("students.html", students=students)


@app.route("/students/new", methods=["GET", "POST"])
@login_required
def students_new():
    exercise = get_current_exercise()
    if not exercise:
        flash("Veuillez d'abord créer ou sélectionner un exercice.", "info")
        return redirect(url_for("exercises_list"))

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
    if not exercise:
        flash("Veuillez d'abord créer ou sélectionner un exercice.", "info")
        return redirect(url_for("exercises_list"))

    contribs = (
        Contribution.query.join(Student)
        .filter(Contribution.exercise_id == exercise.id)
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
        .filter(Contribution.exercise_id == exercise.id)
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
    exercise = get_current_exercise()
    if not exercise:
        flash("Veuillez d'abord créer ou sélectionner un exercice.", "info")
        return redirect(url_for("exercises_list"))

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
            exercise_id=exercise.id,
            amount=amount,
            description=description,
            date=date_obj,
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
    if not exercise:
        flash("Veuillez d'abord créer ou sélectionner un exercice.", "info")
        return redirect(url_for("exercises_list"))

    events = (
        Event.query.filter_by(exercise_id=exercise.id)
        .order_by(Event.start_date.desc().nullslast())
        .all()
    )
    return render_template("events.html", events=events)


@app.route("/events/new", methods=["GET", "POST"])
@login_required
def events_new():
    exercise = get_current_exercise()
    if not exercise:
        flash("Veuillez d'abord créer ou sélectionner un exercice.", "info")
        return redirect(url_for("exercises_list"))

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

        e = Event(
            name=name,
            description=description,
            start_date=start_date,
            end_date=end_date,
            target_budget=target_budget,
            exercise_id=exercise.id,
        )
        db.session.add(e)
        db.session.commit()
        flash("Évènement créé.", "success")
        return redirect(url_for("events_list"))
    return render_template("event_form.html")


@app.route("/events/<int:event_id>")
@login_required
def event_detail(event_id):
    exercise = get_current_exercise()
    if not exercise:
        flash("Veuillez d'abord créer ou sélectionner un exercice.", "info")
        return redirect(url_for("exercises_list"))

    event = Event.query.get_or_404(event_id)
    if event.exercise_id != exercise.id:
        flash("Cet évènement n'appartient pas à l'exercice courant.", "danger")
        return redirect(url_for("events_list"))

    transactions = (
        EventTransaction.query.filter_by(event_id=event_id)
        .order_by(EventTransaction.date.desc())
        .all()
    )
    return render_template("event_detail.html", event=event, transactions=transactions)


@app.route("/events/<int:event_id>/transactions/new", methods=["GET", "POST"])
@login_required
def event_transaction_new(event_id):
    exercise = get_current_exercise()
    if not exercise:
        flash("Veuillez d'abord créer ou sélectionner un exercice.", "info")
        return redirect(url_for("exercises_list"))

    event = Event.query.get_or_404(event_id)
    if event.exercise_id != exercise.id:
        flash("Cet évènement n'appartient pas à l'exercice courant.", "danger")
        return redirect(url_for("events_list"))

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
