from __future__ import with_statement

import hashlib
import threading
import time
import weakref

from pyramid.threadlocal import get_current_request

from pyramid_debugtoolbar.compat import json
from pyramid_debugtoolbar.compat import bytes_
from pyramid_debugtoolbar.compat import url_quote
from pyramid_debugtoolbar.panels import DebugPanel
from pyramid_debugtoolbar.utils import format_sql
from pyramid_debugtoolbar.utils import STATIC_PATH
from pyramid_debugtoolbar.utils import ROOT_ROUTE_NAME

lock = threading.Lock()

try:
    from sqlalchemy import event
    from sqlalchemy.engine.base import Engine

    @event.listens_for(Engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, stmt, params, context, execmany):
        setattr(conn, 'pdtb_start_timer', time.time())

    @event.listens_for(Engine, "after_cursor_execute")
    def _after_cursor_execute(conn, cursor, stmt, params, context, execmany):
        stop_timer = time.time()
        request = get_current_request()
        if request is not None:
            with lock:
                engines = getattr(request.registry, 'pdtb_sqla_engines', {})
                engines[id(conn.engine)] = weakref.ref(conn.engine)
                setattr(request.registry, 'pdtb_sqla_engines', engines)
                queries = getattr(request, 'pdtb_sqla_queries', [])
                queries.append({
                    'engine_id': id(conn.engine),
                    'duration': stop_timer - conn.pdtb_start_timer,
                    'statement': stmt,
                    'parameters': params,
                    'context': context
                })
                setattr(request, 'pdtb_sqla_queries', queries)
        delattr(conn, 'pdtb_start_timer')
                
    has_sqla = True
except ImportError:
    has_sqla = False

_ = lambda x: x


class SQLADebugPanel(DebugPanel):
    """
    Panel that displays the SQL generated by SQLAlchemy plus the time each
    SQL statement took in milliseconds.
    """
    name = 'SQLAlchemy'
    has_content = has_sqla

    @property
    def queries(self):
        return getattr(self.request, 'pdtb_sqla_queries', [])

    def nav_title(self):
        return _('SQLAlchemy')

    def nav_subtitle(self):
        if self.queries:
            count = len(self.queries)
            return "%d %s" % (count, "query" if count == 1 else "queries")

    def title(self):
        return _('SQLAlchemy queries')

    def url(self):
        return ''

    def content(self):
        if not self.queries:
            return 'No queries in executed in request.'

        data = []
        for query in self.queries:
            stmt = query['statement']

            is_select = stmt.strip().lower().startswith('select')
            params = ''
            try:
                params = url_quote(json.dumps(query['parameters']))
            except TypeError:
                pass # object not JSON serializable

            need = self.request.exc_history.token + stmt + params
            hash = hashlib.sha1(bytes_(need)).hexdigest()

            data.append({
                'engine_id': query['engine_id'],
                'duration': query['duration'],
                'sql': format_sql(stmt),
                'raw_sql': stmt,
                'hash': hash,
                'params': params,
                'is_select': is_select,
                'context': query['context'],
            })

        vars = {
            'static_path': self.request.static_url(STATIC_PATH),
            'root_path': self.request.route_url(ROOT_ROUTE_NAME),
            'queries':data,
            }

        delattr(self.request, 'pdtb_sqla_queries')

        return self.render(
            'pyramid_debugtoolbar.panels:templates/sqlalchemy.dbtmako',
            vars, self.request)
