from django.urls import path
from django.contrib.auth import views as av
from django.contrib.auth.views import LogoutView
from django.urls import reverse_lazy
from . import views

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('bienvenida/', views.bienvenida, name='bienvenida'),
    path('recuperar/', av.PasswordResetView.as_view(template_name='form.html', email_template_name='correo_reset.txt', subject_template_name='asunto_reset.txt',
         success_url=reverse_lazy('recuperar_enviado'), extra_context={'titulo': 'Recuperar contraseña', 'subtitulo': 'Escribe tu correo y te enviaremos un enlace.',
         'boton': 'Enviar enlace', 'volver': '/login/'}), name='recuperar'),
    path('recuperar/enviado/', av.PasswordResetDoneView.as_view(template_name='mensaje.html', extra_context={'titulo': 'Revisa tu correo',
         'mensaje': 'Si el correo está registrado, te enviamos un enlace para crear una nueva contraseña. (En modo demostración el mensaje aparece en la terminal del servidor.)'}), name='recuperar_enviado'),
    path('recuperar/listo/', av.PasswordResetCompleteView.as_view(template_name='mensaje.html', extra_context={'titulo': '¡Contraseña actualizada!',
         'mensaje': 'Ya puedes iniciar sesión con tu nueva contraseña.'}), name='recuperar_listo'),
    path('recuperar/<uidb64>/<token>/', av.PasswordResetConfirmView.as_view(template_name='form.html', success_url=reverse_lazy('recuperar_listo'),
         extra_context={'titulo': 'Nueva contraseña', 'subtitulo': 'Elige una contraseña segura.', 'boton': 'Guardar contraseña', 'volver': '/login/'}), name='password_reset_confirm'),
    path('registro/', views.registro, name='registro'),
    path('login/', views.Login.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('pin/', views.pin, name='pin'),
    path('pin/configurar/', views.pin_config, name='pin_config'),
    path('clientes/', views.clientes, name='clientes'),
    path('clientes/<int:pk>/', views.cliente_detalle, name='cliente_detalle'),
    path('deudas/', views.deudas, name='deudas'),
    path('nuevo/<str:tipo>/', views.nuevo, name='nuevo'),
    path('editar/<str:tipo>/<int:pk>/', views.editar, name='editar'),
    path('movimientos/', views.movimientos, name='movimientos'),
    path('ventas/', views.ventas_dia, name='ventas_dia'),
    path('reportes/', views.reportes, name='reportes'),
    path('asistente/', views.asistente, name='asistente'),
]
