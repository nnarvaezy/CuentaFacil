from django.utils import timezone
from .models import Fiado


def alertas(request):
    """Cantidad de fiados vencidos, para la campana de la cabecera."""
    u = request.user
    if not u.is_authenticated or not hasattr(u, 'tienda'):
        return {}
    hoy = timezone.localdate()
    return {'vencidos': sum(1 for f in Fiado.objects.filter(cliente__tienda=u.tienda, vencimiento__lt=hoy) if f.saldo > 0)}
