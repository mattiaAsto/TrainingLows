from flask import render_template

from . import about


@about.route('/')
def about_home():
    return render_template('about.html')
