"""Reglas de negocio y cálculos financieros (RNF-10, RNF-11): los totales los calcula el código, no la IA."""
from datetime import timedelta
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from .models import Fiado, Abono, Gasto, Transferencia, CierreDiario, CATEGORIAS

CERO = Decimal('0.00')
Q = Decimal('0.01')


def suma(qs):
    return (qs.aggregate(s=Sum('monto'))['s'] or CERO).quantize(Q)


def deuda_total(tienda):
    return sum((f.saldo for f in Fiado.objects.filter(cliente__tienda=tienda)), CERO)


def totales_dia(tienda, fecha):
    """Ventas = efectivo del día + transferencias de VENTAS. Los abonos de deudas anteriores no se suman (RF-13)."""
    cierre = CierreDiario.objects.filter(tienda=tienda, fecha=fecha).first()
    efectivo = cierre.ventas_efectivo if cierre else CERO
    tr = Transferencia.objects.filter(tienda=tienda, fecha=fecha)
    t_venta, t_abono = suma(tr.filter(tipo='venta')), suma(tr.filter(tipo='abono'))
    gastos = suma(Gasto.objects.filter(tienda=tienda, fecha=fecha))
    return {'efectivo': efectivo, 'transferencias_venta': t_venta, 'transferencias_abono': t_abono,
            'transferencias': t_venta + t_abono, 'gastos': gastos, 'ventas': efectivo + t_venta}


def dia_cerrado(tienda, fecha):
    return CierreDiario.objects.filter(tienda=tienda, fecha=fecha, cerrado=True).exists()


def cerrar_dia(tienda, fecha):
    t = totales_dia(tienda, fecha)
    c, _ = CierreDiario.objects.get_or_create(tienda=tienda, fecha=fecha)
    c.total_transferencias_venta, c.total_gastos = t['transferencias_venta'], t['gastos']
    c.cerrado, c.cerrado_en = True, timezone.now()
    c.save()
    return c


def reabrir_dia(tienda, fecha):
    CierreDiario.objects.filter(tienda=tienda, fecha=fecha).update(cerrado=False, cerrado_en=None)


@transaction.atomic
def registrar_abono(tienda, fiado_id, monto, metodo, fecha, concepto=''):
    """Un abono nunca supera el saldo (RF-09). Si es por transferencia, queda en el listado de transferencias sin sumarse a ventas."""
    fiado = Fiado.objects.select_for_update().select_related('cliente').get(pk=fiado_id, cliente__tienda=tienda)
    if monto > fiado.saldo:
        raise ValidationError(f'El abono supera la deuda pendiente (${fiado.saldo}).')
    abono = Abono.objects.create(fiado=fiado, monto=monto, metodo=metodo, fecha=fecha)
    if metodo == 'transferencia':
        Transferencia.objects.create(tienda=tienda, monto=monto, fecha=fecha, tipo='abono', abono=abono,
                                     concepto=concepto or f'Abono de {fiado.cliente.nombre}')
    return abono


def resumen_periodo(tienda, desde, hasta):
    rango = {'fecha__gte': desde, 'fecha__lte': hasta}

    def por_dia(qs):
        return {r['fecha']: r['s'].quantize(Q) for r in qs.values('fecha').annotate(s=Sum('monto'))}
    ef = dict(CierreDiario.objects.filter(tienda=tienda, **rango).values_list('fecha', 'ventas_efectivo'))
    tr = Transferencia.objects.filter(tienda=tienda, **rango)
    tv, ta = por_dia(tr.filter(tipo='venta')), por_dia(tr.filter(tipo='abono'))
    ga = por_dia(Gasto.objects.filter(tienda=tienda, **rango))
    dias, d = [], desde
    while d <= hasta:
        e, v = ef.get(d, CERO), tv.get(d, CERO)
        dias.append({'fecha': d, 'ventas': e + v, 'gastos': ga.get(d, CERO)})
        d += timedelta(days=1)
    mayor = max((x['ventas'] for x in dias), default=CERO)
    for x in dias:
        x['alto'] = max(int(x['ventas'] / mayor * 100), 3) if mayor > 0 else 3
    nombres = dict(CATEGORIAS)
    cats = [{'nombre': nombres.get(r['categoria'], r['categoria']), 'total': r['s']}
            for r in Gasto.objects.filter(tienda=tienda, **rango).values('categoria').annotate(s=Sum('monto')).order_by('-s')]
    return {'dias': dias, 'ventas': sum((x['ventas'] for x in dias), CERO), 'gastos': sum(ga.values(), CERO),
            'transferencias': sum(tv.values(), CERO) + sum(ta.values(), CERO), 'categorias': cats}
