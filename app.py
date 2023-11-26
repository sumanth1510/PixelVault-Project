from google.cloud import datastore, storage
from flask import Flask, render_template, request, send_from_directory, send_file, redirect, url_for, g, make_response
import jwt
import os
from datetime import timedelta
import io

JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
BUCKET_NAME = os.environ.get("BUCKET_NAME")

app = Flask(__name__, template_folder="client/templates")

GOOGLE_APPLICATION_CREDENTIALS = os.environ.get('GOOGLE_APPLICATION')
with open('google-credentials.json', 'w') as outfile:
    outfile.write(GOOGLE_APPLICATION_CREDENTIALS)


bucket = storage.Client.from_service_account_json(
    'google-credentials.json').get_bucket(BUCKET_NAME)
client = datastore.Client.from_service_account_json(
    'google-credentials.json')


def check_jwt():
    jwt_cookie = request.cookies.get('jwt')
    print("jwt -", jwt_cookie)

    if jwt_cookie:
        try:
            decoded = jwt.decode(jwt_cookie, JWT_SECRET_KEY, algorithms=[
                'HS256'])

            email = decoded.get('email')
            if email:
                g.email = email
                return True
        except:
            return False

    return False


@app.route('/<path:filename>', endpoint='static_files')
def serve_static_file(filename):
    return send_from_directory("client", filename)


@app.before_request
def protect():
    if request.endpoint == "static_files":
        return
    if check_jwt():
        if request.endpoint == "login" or request.endpoint == "signup":
            return redirect("/")
    elif request.endpoint != "login" and request.endpoint != "signup":
        return redirect(url_for('login'))


def get_user(email):
    query = client.query(kind='User')
    query.add_filter('email', '=', email)
    return query.fetch()


def add_user(email, password):
    key = client.key('User')
    entity = datastore.Entity(key)
    entity.update({
        'email': email,
        'password': password
    })
    client.put(entity)


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    message = ''
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = list(get_user(email))
        if user:
            message = 'Email already exists!'
        else:
            add_user(email, password)
            return redirect(url_for('login'))
    return render_template('signup.html', message=message)


@app.route('/login', methods=['GET', 'POST'])
def login():
    message = ''
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = list(get_user(email))

        if user and user[0]['password'] == password:
            token = jwt.encode(
                {'email': email}, JWT_SECRET_KEY, algorithm='HS256')

            response = make_response(redirect(url_for("index")))
            response.set_cookie("jwt", token, httponly=True)
            return response

        message = 'Invalid email or password!'
    return render_template('login.html', message=message)


@app.route("/logout", methods=["POST"])
def logout():
    response = make_response(redirect(url_for("login")))
    response.set_cookie('jwt', '', expires=0)
    return response


def sizeOfImage(image):
    image_size_kb = image['image_size'] / 1024
    image_size_mb = image_size_kb / 1024
    print(image)
    if image_size_mb > 1:
        image['image_size'] = f"{round(image_size_mb, 2)} mb"
    else:
        image['image_size'] = f"{round(image_size_kb, 2)} kb"
    return image['image_size']


@app.route('/')
def index():
    email = g.get("email")

    query = client.query(kind='Image')
    query.add_filter('user', '=', email)
    images = list(query.fetch())

    # print(images)

    image_urls = [{"id": image['id'], "name": image["filename"], 'size': sizeOfImage(image), 'url': f'/download/{image["id"]}'}
                  for image in images]

    return render_template('index.html', images=image_urls)


@app.route('/upload', methods=['POST'])
def upload_files():
    if 'images' not in request.files:
        return redirect(url_for('index'))

    files = request.files.getlist('images')

    if not files or all([f.filename == '' for f in files]):
        return redirect(url_for('index'))
    username = g.get("email")
    for file in files:
        if file:
            filename = file.filename
            sec_name = username + \
                filename.replace(' ', '_').replace('/', '_').lower()
            blob = bucket.blob(sec_name)
            blob.upload_from_string(
                file.read(),
                content_type=file.content_type
            )

            image_entity = datastore.Entity(key=client.key('Image'))
            image_entity.update({
                'user': g.get("email"),
                'filename': filename,
                'image_size': blob.size,
                'id': sec_name,
            })
            client.put(image_entity)

    return render_template('success.html')


@app.route('/image/<filename>')
def get_image(filename):
    blob = bucket.blob(filename)
    signed_url = blob.generate_signed_url(
        version='v4',
        expiration=timedelta(minutes=30),
        method='GET'
    )
    return redirect(signed_url)


@app.route('/download/<filename>')
def download_image(filename):
    blob = bucket.blob(filename)
    signed_url = blob.generate_signed_url(
        version='v4',
        expiration=timedelta(minutes=30),
        method='GET'
    )
    return redirect(signed_url)


@app.route('/delete/<filename>')
def delete_image(filename):
    if not g.get("email"):
        return redirect(url_for('login'))
    blob = bucket.blob(filename)
    blob.delete()
    query = client.query(kind='Image')
    query.add_filter('id', '=', filename)
    images = list(query.fetch())
    for image in images:
        client.delete(image.key)

    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
