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
user=User(id=999999,email='fixture@example.invalid',username='fixture@example.invalid',first_name='Prueba',is_test=True)
machine=Machine(owner=user,title='Borrador de prueba',data={'hours':0,'brand':'Original','location':'Prueba, sin inventario','power':'100 kW'})
state={'id':str(machine.id),'revision':1,'title':machine.title,'category':None,'data':machine.data,'provenance':{},'editable':True,'status':'draft'}
assets=[SimpleNamespace(id=str(i),kind=k,purpose=p,is_cover=i==1) for i,k,p in [(1,'image','general'),(2,'image','plate'),(3,'image','document'),(4,'video','general')]]
context={'can_delete_draft':True,'csrf_token':'a'*64,'machine':machine,'data':machine.data,'provenance':{},'machine_json':state,'assets':assets,'categories':[],'categories_json':[],'catalog_models_json':[],'catalog_brands':[],'step':1,'user':user,'request':SimpleNamespace(path=f'/panel/maquinarias/{machine.id}/'),'analytics_settings':{'enabled':False}}
with override_settings(STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}}):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stdout.write(render_to_string('portal/wizard.html',context))
