"""Task configuration independence, authorization, optimistic revisions and no execution."""
from copy import deepcopy
from sqlalchemy import MetaData, Table, Column, Integer, String, Boolean, JSON, DateTime, select, update, func, text
from test_agents_workspace import WorkspaceFixture, DEFINITION, HEADERS
from agent_engine import models as m


class TaskConfigurationTests(WorkspaceFixture):
    def setUp(self):
        super().setUp()
        self.login()
        self.agent = self.create().json['agent']
        with self.engine.begin() as conn:
            conn.execute(update(m.agents).where(m.agents.c.id == self.agent['id']).values(legacy_agent_id=11))
        self.tasks = Table('agente_tareas', MetaData(), Column('id', Integer, primary_key=True),
            Column('agente_id', Integer), Column('ae_agent_id', String(36)), Column('tipo', String(30)),
            Column('nombre', String(150)), Column('habilitada', Boolean), Column('parametros', JSON),
            Column('actualizado_en', DateTime))
        self.tasks.metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            conn.execute(self.tasks.insert(), [dict(id=i, agente_id=11, ae_agent_id=self.agent['id'] if i==1 else None,
                tipo='PRODUCTOS_NUEVOS', nombre='Tarea '+str(i), habilitada=True,
                parametros={'schema_version':1,'scope_ids':[108],'category_ids':[975]}) for i in (1,2)])
        self.url = '/api/agents/v1/agents/'+self.agent['id']+'/configured-tasks'

    def test_independent_revisioned_configuration_and_no_execution(self):
        self.assertEqual(len(self.client.get(self.url).json['items']),2)
        original = self.client.get(self.url+'/2').json['task']
        body = deepcopy(DEFINITION)|{'name':'Tarea individual','expected_revision':1,'instructions':'Solo tarea 1'}
        response = self.client.patch(self.url+'/1', json=body, headers=HEADERS)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['task']['revision'],2)
        self.assertEqual(self.client.get(self.url+'/1').json['task']['configuration']['instructions'],'Solo tarea 1')
        self.assertEqual(self.client.get(self.url+'/2').json['task'],original)
        self.assertEqual(self.client.patch(self.url+'/1',json=body,headers=HEADERS).status_code,409)
        with self.engine.connect() as conn:
            agent = conn.execute(select(m.agents)).mappings().one()
            self.assertEqual(agent['instructions'], DEFINITION['instructions'])
            self.assertEqual(agent['revision'],1)
            self.assertEqual(agent['configuration_state'],'DISABLED')
            self.assertEqual(conn.execute(select(func.count()).select_from(m.jobs)).scalar(),0)
            self.assertEqual(conn.execute(select(func.count()).select_from(m.schedules)).scalar(),0)
            params = conn.execute(select(self.tasks.c.parametros).where(self.tasks.c.id==1)).scalar()
            self.assertEqual(params['scope_ids'],[108])

    def test_owner_admin_and_csrf_boundaries(self):
        body = DEFINITION|{'expected_revision':1}
        self.assertEqual(self.client.patch(self.url+'/1',json=body).status_code,403)
        self.assertEqual(self.client.patch(self.url+'/1',json=body,headers=HEADERS|{'Origin':'https://evil.test'}).status_code,403)
        self.login(2)
        self.assertEqual(self.client.get(self.url+'/1').status_code,404)
        self.assertEqual(self.client.patch(self.url+'/1',json=body,headers=HEADERS).status_code,404)
        admin_url=self.url.replace('/agents/v1/agents/','/agents/v1/admin/agents/')+'/1'
        self.assertEqual(self.client.get(admin_url).status_code,403)
        self.assertEqual(self.client.get('/api/agents/v1/admin/configured-tasks').status_code,403)
        self.login(99)
        self.assertEqual(self.client.get(admin_url).status_code,200)
        self.assertEqual(self.client.patch(admin_url,json=body,headers=HEADERS).status_code,200)
        items=self.client.get('/api/agents/v1/admin/configured-tasks?limit=1').json
        self.assertEqual(len(items['items']),1)
        self.assertEqual(items['next_cursor'],1)
        self.assertEqual(self.client.get('/api/agents/v1/admin/configured-tasks?after=1').json['items'][0]['id'],2)
        self.assertEqual(self.client.get(self.url+'/1').status_code,404) # Admin owner route stays scoped.

    def test_deleted_and_mismatched_tasks_never_editable(self):
        with self.engine.begin() as conn:
            conn.execute(self.tasks.update().where(self.tasks.c.id==1).values(parametros={'_deleted_at':'2026-11-12'}))
        self.assertEqual(self.client.get(self.url+'/1').status_code,404)
        self.assertEqual(len(self.client.get(self.url).json['items']),1)
        with self.engine.begin() as conn:
            conn.execute(self.tasks.update().where(self.tasks.c.id==2).values(ae_agent_id='foreign-agent'))
        self.assertEqual(self.client.get(self.url+'/2').status_code,409)

    def test_identity_preserves_tool_defaults_and_task_configuration(self):
        # Email-derived linked identity is verified by the existing agent manager.
        with self.engine.begin() as conn:
            conn.execute(text('ALTER TABLE usuarios ADD COLUMN correo_electronico VARCHAR(120)'))
            conn.execute(text("UPDATE usuarios SET correo_electronico='owner@example.test' WHERE id=1"))
        body={k:DEFINITION[k] for k in ('name','description','instructions','timezone')}
        response=self.client.patch('/api/agents/v1/agents/'+self.agent['id']+'/identity',json=body|{'expected_revision':1},headers=HEADERS)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['agent']['search_parameters'],DEFINITION['tool_parameters'])
        self.assertEqual(response.json['agent']['limits'],DEFINITION['limits'])
        self.assertFalse(self.client.get(self.url+'/1').json['task']['configured'])
