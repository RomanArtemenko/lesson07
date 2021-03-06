import os
import redis
from urllib.parse import urlparse
from werkzeug.wrappers import Request, Response
from werkzeug.routing import Map, Rule
from werkzeug.exceptions import HTTPException, NotFound
from werkzeug.wsgi import SharedDataMiddleware
from werkzeug.utils import redirect
from jinja2 import Environment, FileSystemLoader
from datetime import datetime


def base36_encode(number):
    assert number >= 0, 'positive integer required'
    if number == 0:
        return '0'
    base36 = []
    while number != 0:
        number, i = divmod(number, 36)
        base36.append('0123456789abcdefghijklmnopqrstuvwxyz'[i])
    return ''.join(reversed(base36))

def is_valid_user(user):
    return bool(user) and len(user) <= 30

def is_valid_header(header):
    return bool(header) and len(header) <= 50

def is_valid_comment(comment):
    return bool(comment) and len(comment) <= 255

def get_hostname(url):
    return urlparse(url).netloc


class Ad(object):

    def __init__(self, config):
        self.redis = redis.Redis(config['redis_host'], config['redis_port'], decode_responses=True)
        template_path = os.path.join(os.path.dirname(__file__), 'templates')
        self.jinja_env = Environment(loader=FileSystemLoader(template_path),
                                     autoescape=True)
        self.jinja_env.filters['hostname'] = get_hostname

        self.url_map = Map([
            Rule('/', endpoint='board'),
            Rule('/ad/<int:id>', endpoint='advertisement'),
            Rule('/ad/<int:id>/add_comment', endpoint='add_comment'),
            Rule('/add', endpoint='add_advertisement'),
        ])

    def on_board(self, request):
        ads = self.redis.keys('ad:*')
        ad_list = []

        for ad in ads:
            ad_id = ad.split(":")[1]
            ad_header = self.redis.get(ad)
            ad_user = self.redis.get('user:%s' % ad)
            ad_date = self.redis.get('date:%s' % ad)
             
            ad_list.append({'id': ad_id, 'header': ad_header, 'user': ad_user, 'date': ad_date })

        return self.render_template('index.html', ad_list=ad_list)

    def on_add_advertisement(self, request):
        error = None
        if request.method == 'POST':
            user = request.form['user']
            header = request.form['header']
            
            if not(is_valid_user(user) and is_valid_header(header)):
                error = "Please enter a valid data!"
            else: 
                self._insert_advertisement(user, header)            
                return redirect('/')            
        return self.render_template('add_advertisement.html', error=error)

    def on_advertisement(self, request, id):
        ad = 'ad:%s' % id
        ad_header = self.redis.get(ad)
        ad_user = self.redis.get('user:%s' % ad)
        ad_date = self.redis.get('date:%s' % ad)
        
        ad_obj = {'id': id, 'header': ad_header, 'user': ad_user, 'date': ad_date}

        ad_comments = self.redis.keys('comment:*:%s' % ad)        
        comment_list = []

        for comment in ad_comments:
            com_id = comment.split(':')[1]
            com_text = self.redis.get('comment:%s:%s' % (com_id, ad))
            com_user = self.redis.get('user:comment:%s:%s' % (com_id, ad))
            com_date = self.redis.get('date:comment:%s:%s' % (com_id, ad))

            comment_list.append({'id': com_id, 'text': com_text, 'user': com_user, 'date': com_date })

        return self.render_template('advertisement.html', ad_obj=ad_obj, comment_list=comment_list)

    def on_add_comment(self, request, id):
        error = None
        if request.method == 'POST':
            user = request.form['user']
            text = request.form['text']
            
            if not(is_valid_user(user) and is_valid_comment(text)):
                error = "Please enter a valid data!"
            else: 
                self._insert_comment(id, user, text)            
                return redirect('/ad/%s' % id)            
        return self.render_template('add_comment.html', error=error)
        
    def _insert_advertisement(self, user, header):
        id = self.redis.incr('ad_counter')

        self.redis.set('ad:%s' % id ,header)
        self.redis.set('user:ad:%s' % id, user)
        self.redis.set('date:ad:%s' % id, self._time_stamp())

    def _insert_comment(self, ad_id, user, text):
        id = self.redis.incr('comment_counter')
        print('ID : ' + str(id))
        self.redis.set('comment:%s:ad:%s' % (id, ad_id), text)
        self.redis.set('user:comment:%s:ad:%s' % (id, ad_id), user)
        self.redis.set('date:comment:%s:ad:%s' % (id, ad_id), self._time_stamp())
    
    def _time_stamp(self):
        return  datetime.strftime(datetime.now(), "%Y-%m-%d %H:%M")

    def error_404(self):
        response = self.render_template('404.html')
        response.status_code = 404
        return response

    def render_template(self, template_name, **context):
        t = self.jinja_env.get_template(template_name)
        return Response(t.render(context), mimetype='text/html')

    def dispatch_request(self, request):
        adapter = self.url_map.bind_to_environ(request.environ)
        try:
            endpoint, values = adapter.match()
            return getattr(self, 'on_' + endpoint)(request, **values)
        except NotFound as e:
            return self.error_404()
        except HTTPException as e:
            return e

    def wsgi_app(self, environ, start_response):
        request = Request(environ)
        response = self.dispatch_request(request)
        return response(environ, start_response)

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)

def create_app(redis_host='localhost', redis_port=6379, with_static=True):
    app = Ad({
        'redis_host':       redis_host,
        'redis_port':       redis_port
    })
    if with_static:
        app.wsgi_app = SharedDataMiddleware(app.wsgi_app, {
            '/static':  os.path.join(os.path.dirname(__file__), 'static')
        })
    return app


if __name__ == '__main__':
    from werkzeug.serving import run_simple
    app = create_app()
    run_simple('127.0.0.1', 5000, app, use_debugger=True, use_reloader=True)