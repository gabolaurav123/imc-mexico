import os,sys
from pathlib import Path
from types import SimpleNamespace
os.environ['DATABASE_URL']='sqlite:///:memory:'
os.environ['DIRECT_URL']=''
os.environ['DJANGO_SETTINGS_MODULE']='config.settings'
os.environ['DEBUG']='true'
REPO=Path(__file__).resolve().parents[2]
os.chdir(REPO)
sys.path.insert(0,str(REPO))
import django
django.setup()
from django.template.loader import render_to_string
from django.test.utils import override_settings
from portal.models import User,Machine
from portal.category_profiles import EXCAVATOR_PROFILE
user=User(id=999999,email='fixture@example.invalid',username='fixture@example.invalid',first_name='Prueba',is_test=True)
excavator = '--excavator' in sys.argv
guest = '--guest' in sys.argv
categories = []
category_data = []
if excavator:
    selected = {'id': 701, 'name': 'Excavadoras', 'slug': 'excavadoras', 'fields': []}
    generic = {'id': 702, 'name': 'Montacargas', 'slug': 'montacargas', 'fields': []}
    categories = [selected, generic]
    category_data = [{**selected, 'aliases': ['excavadora'], 'profile': EXCAVATOR_PROFILE},
                     {**generic, 'aliases': ['montacargas'], 'profile': {}}]
machine=Machine(owner=user,title='Borrador de prueba',category_id=701 if excavator else None,
                data={'hours':0,'brand':'Original','location':'Prueba, sin inventario','power':'100 kW',
                      **({'power_type': 'net'} if excavator else {})})
state={'id':str(machine.id),'revision':1,'title':machine.title,'category':701 if excavator else None,'data':machine.data,'provenance':{},'editable':True,'status':'draft'}
assets=[SimpleNamespace(id=str(i),kind=k,purpose=p,is_cover=i==1) for i,k,p in [(1,'image','general'),(2,'image','plate'),(3,'image','document'),(4,'video','general')]]
guest_draft = SimpleNamespace(id='guest-draft-fixture') if guest else None
context={'can_export':not guest,'can_delete_draft':not guest,'csrf_token':'a'*64,'machine':machine,'data':machine.data,'provenance':{},'machine_json':state,'assets':assets,'categories':categories,'categories_json':category_data,'catalog_models_json':[],'catalog_brands':[],'step':1,'user':user,'request':SimpleNamespace(path=f'/panel/maquinarias/{machine.id}/'),'analytics_settings':{'enabled':False},'guest_draft':guest_draft,'guest_api_base':'/api/invitados/guest-draft-fixture/' if guest else '', 'settings_context':{'max_images':3} if guest else None}
with override_settings(STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}}):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stdout.write(render_to_string('portal/wizard.html',context))
