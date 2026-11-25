from django import template

register = template.Library()
ICONOS = {'username': 'mail', 'email': 'mail', 'first_name': 'user', 'nombre_tienda': 'store', 'password': 'lock', 'password1': 'lock',
          'password2': 'lock', 'new_password1': 'lock', 'new_password2': 'lock', 'pin': 'lock', 'pin2': 'lock', 'telefono': 'phone',
          'cedula': 'user', 'direccion': 'pin', 'monto': 'dollar', 'fecha': 'cal', 'vencimiento': 'cal', 'cliente': 'user', 'fiado': 'file',
          'nombre': 'user', 'referencia': 'file', 'concepto': 'file', 'descripcion': 'file', 'categoria': 'tag', 'metodo': 'dollar',
          'tipo': 'repeat', 'ventas_efectivo': 'dollar'}
CATEGORIAS = {'servicios': 'zap', 'transporte': 'truck', 'suministros': 'box', 'mercaderia': 'cart', 'otros': 'tag'}


@register.filter
def icono(nombre):
    return ICONOS.get(nombre, '')


@register.filter
def ic_gasto(categoria):
    return CATEGORIAS.get(categoria, 'tag')


@register.filter
def iniciales(nombre):
    p = nombre.split()
    return (p[0][0] + (p[1][0] if len(p) > 1 else '')).upper() if p else '?'


@register.filter
def primer_nombre(nombre):
    p = (nombre or '').split()
    return p[0] if p else 'tendero'
