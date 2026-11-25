import time
from django.conf import settings
from django.shortcuts import redirect

LIBRES = {
    '/pin/',
    '/pin/configurar/',
    '/login/',
    '/logout/',
    '/registro/',
}
PREFIJOS = ('/admin/', '/static/')


class BloqueoPinMiddleware:
    """Bloquea la sesión (pide PIN) tras inactividad o si aún no se desbloqueó (RNF-03)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        u = request.user
        if u.is_authenticated and request.path not in LIBRES and not request.path.startswith(PREFIJOS):
            tienda = getattr(u, 'tienda', None)
            if tienda and tienda.pin_hash:
                ahora = time.time()
                ultima = request.session.get('ultima', 0)
                if not request.session.get('desbloqueado') or ahora - ultima > settings.PIN_INACTIVIDAD_SEGUNDOS:
                    request.session['desbloqueado'] = False
                    return redirect('pin')
                request.session['ultima'] = ahora
        return self.get_response(request)
