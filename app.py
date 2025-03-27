from flask import Flask, render_template, redirect, url_for, Response, send_from_directory, request
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from wtforms import StringField, FileField
from wtforms.validators import DataRequired
import os
import cv2
import face_recognition
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Configuration settings
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///students.db'
app.config['SECRET_KEY'] = "your_secret_key"
app.config['UPLOAD_FOLDER'] = 'media'
app.config['ALLOWED_EXTENSIONS'] = {'jpg', 'jpeg', 'png', 'gif'}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

video_capture = None
users_data = {}  # Dictionary to store user data (name and face encoding)

# Database Model
class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    studentID = db.Column(db.String(10), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    roll_no = db.Column(db.String(20), nullable=False)
    class_name = db.Column(db.String(50), nullable=False)
    photo = db.Column(db.String(100), nullable=True)

# Student Form
class StudentForm(FlaskForm):
    studentID = StringField('Student ID', validators=[DataRequired()])
    name = StringField('Name', validators=[DataRequired()])
    roll_no = StringField('Roll No', validators=[DataRequired()])
    class_name = StringField('Class', validators=[DataRequired()])
    photo = FileField('Photo')

with app.app_context():
    db.create_all()  # Ensure the database tables exist

@app.route('/add_student', methods=['GET', 'POST'])
def add_student():
    form = StudentForm()
    if form.validate_on_submit():
        student = Student(
            studentID=form.studentID.data,
            name=form.name.data,
            roll_no=form.roll_no.data,
            class_name=form.class_name.data
        )

        # Handle photo upload securely
        file = form.photo.data
        if allowed_file(file.filename):
            filename = secure_filename(f"{form.name.data}_{form.roll_no.data}_{form.studentID.data}.jpg")
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            student.photo = filename

            # Extract face encoding and store it
            image = face_recognition.load_image_file(file_path)
            face_encodings = face_recognition.face_encodings(image)
            if face_encodings:
                users_data[form.name.data] = face_encodings[0].tolist()

            db.session.add(student)
            db.session.commit()
            return redirect(url_for('students'))

    return render_template('add_student.html', form=form)

def detect_faces():
    global video_capture

    if video_capture is None:
        video_capture = cv2.VideoCapture(0)

    while True:
        ret, frame = video_capture.read()
        if not ret:
            break

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        face_locations = face_recognition.face_locations(rgb_frame)
        face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

        for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
            details = recognize_face(face_encoding)

            cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)

            # Display name, ID, and email correctly
            if details:
                y_offset = top - 40  # Start displaying above the face
                for line in details.split(", "):
                    cv2.putText(frame, line, (left, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                    y_offset += 20  # Move down for next line
            else:
                cv2.putText(frame, "Unknown", (left, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

        ret, jpeg = cv2.imencode('.jpg', frame)
        frame = jpeg.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')


def recognize_face(face_encoding):
    known_encodings = list(users_data.values())
    known_filenames = list(users_data.keys())

    if not known_encodings:
        return None

    matches = face_recognition.compare_faces(known_encodings, face_encoding, tolerance=0.6)
    face_distances = face_recognition.face_distance(known_encodings, face_encoding)

    if True in matches:
        best_match_index = face_distances.argmin()
        filename = known_filenames[best_match_index]

        # Extract name, ID, and email from the filename
        filename_without_extension = os.path.splitext(filename)[0]  # Remove .jpeg or .png
        name, student_id, rollno = filename_without_extension.split("_")  # Split by "_"

        return f"{name}, {student_id}, {rollno}"

    return None


@app.route('/video_feed')
def video_feed():
    return Response(detect_faces(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/delete_student/<int:id>', methods=['POST'])
def delete_student(id):
    student = Student.query.get(id)
    if student:
        if request.method == 'POST':
            if student.photo in users_data:
                del users_data[student.photo]

            if student.photo:
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], student.photo)
                if os.path.exists(file_path):
                    os.remove(file_path)

            db.session.delete(student)
            db.session.commit()
    return redirect(url_for('students'))

@app.route('/')
def home():
    global video_capture

    if video_capture is not None:
        video_capture.release()
        cv2.destroyAllWindows()
        video_capture = None

    return render_template('Home.html')

@app.route('/students')
def students():
    page = request.args.get('page', 1, type=int)
    students = Student.query.paginate(page=page, per_page=10)
    return render_template('students.html', students=students)

@app.route('/live')
def live():
    return render_template('video_feed_live.html')

@app.route('/media/<filename>')
def media(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/load_faces')
def load_faces():
    global users_data
    users_data.clear()

    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        if allowed_file(filename):
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            encoding = get_face_encoding(file_path)
            if encoding:
                users_data[filename] = encoding.tolist()

    return "Face data loaded", 200

def get_face_encoding(image_path):
    """Load face encoding only when needed"""
    image = face_recognition.load_image_file(image_path)
    encodings = face_recognition.face_encodings(image)
    return encodings[0] if encodings else None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

if __name__ == '__main__':
    # Load known faces when the app starts
   for filename in os.listdir(app.config['UPLOAD_FOLDER']):
    if allowed_file(filename):
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        encoding = get_face_encoding(file_path)

        if encoding is not None and len(encoding) > 0:
            users_data[filename] = encoding.tolist()

                
    app.run(debug=True, host='0.0.0.0', port=8000)
