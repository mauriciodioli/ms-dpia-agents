"""Real-browser task editing and the one-column administrative selector."""
import os
import threading
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from test_agents_workspace import WorkspaceFixture
from sqlalchemy import MetaData, Table, Column, Integer, String, Boolean, JSON, DateTime, update, text, select
from playwright.sync_api import expect
import test_agents_workspace_ui as browser_fixture
from agent_engine import models as m


class ConfiguredTaskBrowserTests(WorkspaceFixture):
    stop_server = browser_fixture.WorkspaceBrowserTests.stop_server
    browser_login = browser_fixture.WorkspaceBrowserTests.browser_login

    def setUp(self):
        super().setUp()
        self.server = make_server('127.0.0.1', 0, self.app, threaded=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.pw = sync_playwright().start()
        self.addCleanup(self.pw.stop)
        self.browser = self.pw.chromium.launch(executable_path=os.environ.get('CHROME_BIN','/usr/bin/chromium'), args=['--no-sandbox'])
        self.addCleanup(self.browser.close)
        self.context = self.browser.new_context(viewport={'width':1440,'height':1000}, reduced_motion='reduce')
        self.context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(self.base+'/') else route.abort())
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.browser_login(1)

    def seed_tasks(self):
        self.login()
        self.agent = self.create().json['agent']
        tasks = Table('agente_tareas', MetaData(), Column('id', Integer, primary_key=True),
            Column('agente_id', Integer), Column('ae_agent_id', String(36)), Column('tipo', String(30)),
            Column('nombre', String(150)), Column('habilitada', Boolean), Column('parametros', JSON),
            Column('actualizado_en', DateTime))
        tasks.metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            conn.execute(text('ALTER TABLE usuarios ADD COLUMN correo_electronico VARCHAR(120)'))
            conn.execute(text("UPDATE usuarios SET correo_electronico='owner@example.test' WHERE id=1"))
            conn.execute(update(m.agents).where(m.agents.c.id==self.agent['id']).values(legacy_agent_id=11))
            conn.execute(tasks.insert(),[dict(id=i,agente_id=11,ae_agent_id=self.agent['id'],tipo='PRODUCTOS_NUEVOS',
                nombre='Tarea '+str(i),habilitada=True,parametros={'schema_version':1}) for i in (1,2)])
        self.tasks=tasks

    def test_task_editor_and_general_editor_are_independent(self):
        self.seed_tasks()
        self.page.goto(self.base+'/agents/'+self.agent['id']+'/edit')
        expect(self.page.get_by_role('heading',name='Configurar agente',exact=True)).to_be_visible()
        expect(self.page.get_by_role('link',name='Tarea 1',exact=True)).to_be_visible()
        expect(self.page.get_by_label('Instrucciones adicionales',exact=True)).to_have_count(0)
        self.page.get_by_role('link',name='Tarea 1',exact=True).click()
        expect(self.page.get_by_role('heading',name='Configurar tarea',exact=True)).to_be_visible()
        self.page.get_by_label('Instrucciones de la tarea',exact=True).fill('Solo tarea uno')
        self.page.get_by_label('Instrucciones adicionales',exact=True).fill('Resumen específico')
        self.page.get_by_role('button',name='Guardar cambios',exact=True).click()
        expect(self.page.get_by_role('heading',name='Mis agentes',exact=True)).to_be_visible()
        self.page.goto(self.base+'/agents/'+self.agent['id']+'/tasks/1/edit')
        expect(self.page.get_by_label('Instrucciones de la tarea',exact=True)).to_have_value('Solo tarea uno')
        with self.engine.connect() as conn:
            params=conn.execute(select(self.tasks.c.parametros).where(self.tasks.c.id==2)).scalar()
            self.assertNotIn('_agent_configuration',params)
        self.assertEqual(self.errors,[])

    def test_admin_single_column_opens_another_owners_task(self):
        self.seed_tasks()
        self.browser_login(99)
        self.page.goto(self.base+'/administration')
        section=self.page.locator('section.panel').filter(has=self.page.get_by_role('heading',name='Tareas configuradas',exact=True))
        expect(section.locator('th')).to_have_count(1)
        section.get_by_role('link',name='Tarea 2',exact=True).click()
        expect(self.page.get_by_role('heading',name='Configurar tarea',exact=True)).to_be_visible()
        self.page.get_by_label('Instrucciones de la tarea',exact=True).fill('Revisión administrativa')
        self.page.get_by_role('button',name='Guardar cambios',exact=True).click()
        expect(self.page.get_by_role('heading',name='Administración',exact=True)).to_be_visible()
        with self.engine.connect() as conn:
            params=conn.execute(select(self.tasks.c.parametros).where(self.tasks.c.id==2)).scalar()
            self.assertEqual(params['_agent_configuration']['instructions'],'Revisión administrativa')
        self.assertEqual(self.errors,[])
