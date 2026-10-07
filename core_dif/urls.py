from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from ciudadanos import views 

from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls), 
    
    # --- TUS RUTAS ---
    path('', views.inicio, name='inicio'),
    path('registro/', views.registro, name='registro'),
    path('activar/<uidb64>/<token>/', views.activar_cuenta, name='activar_cuenta'),
    path('entrar/', views.iniciar_sesion, name='iniciar_sesion'),
    path('salir/', views.cerrar_sesion, name='cerrar_sesion'),
    path('api/procesar-curp/', views.procesar_curp_pdf, name='procesar_curp_pdf'),
    path('mi-perfil/', views.perfil_ciudadano, name='perfil'),
    
    # --- RUTAS NATIVAS DE RECUPERACIÓN DE CONTRASEÑA ---
    path('recuperar-password/', auth_views.PasswordResetView.as_view(template_name='password_reset_form.html'), name='password_reset'),
    path('recuperar-password/enviado/', auth_views.PasswordResetDoneView.as_view(template_name='password_reset_done.html'), name='password_reset_done'),
    path('recuperar-password/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='password_reset_confirm.html'), name='password_reset_confirm'),    
    path('recuperar-password/completo/', auth_views.PasswordResetCompleteView.as_view(template_name='password_reset_complete.html'), name='password_reset_complete'),


    ##- ---------- RUTAS DE TRAMITES JAREE

    path('tramite/<int:tramite_id>/iniciar/', views.iniciar_tramite, name='iniciar_tramite'),
    path('mis-tramites/', views.mis_tramites, name='mis_tramites'),
    path('funcionario/login/', views.login_funcionario, name='login_funcionario'),
    path('funcionario/panel/', views.panel_funcionario, name='panel_funcionario'),
    path('funcionario/revisar/<int:solicitud_id>/', views.revisar_solicitud, name='revisar_solicitud'),

    path('mis-tramites/detalle/<int:solicitud_id>/', views.corregir_solicitud, name='corregir_solicitud'),
    path('cita/<int:solicitud_id>/agendar/', views.agendar_cita, name='agendar_cita'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)