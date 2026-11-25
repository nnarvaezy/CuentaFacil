"""Asistente de CuentaFácil (Etapa 4). Interpreta mensajes por REGLAS, sin IA externa.
Los totales los calculan las funciones de servicios.py (RNF-11). Todo registro pide confirmación (RNF-06).
Este módulo no conoce la interfaz: recibe texto y devuelve texto (RNF-10, RF-22)."""
import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import formats, timezone
from . import servicios, gemini
from difflib import SequenceMatcher
from .models import Cliente, Fiado, Gasto, Transferencia, CATEGORIAS


CERRADO = 'Ese día está cerrado. Reabre el cierre en Ventas para registrar.'
AYUDA = ('Puedo ayudarte con:\n'
         '• Consultas: «ventas de hoy», «gastos de la semana», «transferencias del mes», «cuánto debe Juan», «quién me debe».\n'
         '• Registros (te pido confirmar): «registra un gasto de 10 en servicios», «Juan abonó 5», '
         '«transferencia de 12 por una venta», «fiado de 20 para Juan».\n'
         '• Promociones: «promoción para 20 yogures a 1,50 que vencen en 3 días».')
NUM = r'\d+(?:[.,]\d{1,2})?'
DECENAS = {'veinte': 20, 'treinta': 30, 'cuarenta': 40, 'cincuenta': 50, 'sesenta': 60, 'setenta': 70, 'ochenta': 80, 'noventa': 90}
UNIDADES = {'dos': 2, 'tres': 3, 'cuatro': 4, 'cinco': 5, 'seis': 6, 'siete': 7, 'ocho': 8, 'nueve': 9, 'diez': 10, 'once': 11,
            'doce': 12, 'trece': 13, 'catorce': 14, 'quince': 15, 'dieciseis': 16, 'diecisiete': 17, 'dieciocho': 18,
            'diecinueve': 19, 'veinte': 20, 'veintiuno': 21, 'veintidos': 22, 'veintitres': 23, 'veinticuatro': 24, 'veinticinco': 25, 'veintiseis': 26, 'veintisiete': 27, 'veintiocho': 28, 'veintinueve': 29, 'cien': 100, **DECENAS}
CATEGORIA_CLAVES = {'servicios': ('servicio', 'luz', 'agua', 'internet'), 'transporte': ('transporte', 'pasaje', 'gasolina', 'taxi', 'flete'),
                    'suministros': ('suministro', 'funda', 'limpieza'), 'mercaderia': ('mercaderia', 'mercancia', 'inventario', 'producto')}
NO_NOMBRE = {'hoy', 'ayer', 'total', 'todos', 'todo', 'semana', 'mes', 'pendiente', 'pendientes', 'cliente', 'clientes', 'fiados', 'fiado',
             'por', 'los', 'las', 'del', 'con', 'mis', 'yo'}


def norm(s):
    s = unicodedata.normalize('NFD', s.lower())
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn')


def m(x):
    return '$' + formats.number_format(Decimal(x), decimal_pos=2, use_l10n=True)


def dec(s):
    return Decimal(s.replace(',', '.'))


def resp(texto, enlace=None, confirmar=False):
    return {'texto': texto, 'enlace': enlace, 'confirmar': confirmar}


def palabras_a_digitos(t):
    t = re.sub(r'\b(' + '|'.join(DECENAS) + r') y (uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve)\b',
               lambda x: str(DECENAS[x.group(1)] + UNIDADES[x.group(2)]) if x.group(2) != 'uno' else str(DECENAS[x.group(1)] + 1), t)
    return re.sub(r'\b(' + '|'.join(UNIDADES) + r')\b', lambda x: str(UNIDADES[x.group(1)]), t)


def extraer_monto(t):
    for patron in (r'\$\s*(' + NUM + ')', '(' + NUM + r')\s*(?:dolar|dolares|usd)'):
        x = re.search(patron, t)
        if x:
            return dec(x.group(1))
    x = re.search(r'(?<![\w.,$])(' + NUM + r')(?![\w])', t)
    return dec(x.group(1)) if x else None

def buscar_clientes(tienda, t):
    """Busca clientes exactos, parciales y similares de esta tienda."""

    t = ' ' + re.sub(r'[^a-z0-9]+', ' ', norm(t)) + ' '

    exactos = []
    parciales = []
    similares = []

    palabras = [
        p for p in t.split()
        if len(p) >= 4 and p not in NO_NOMBRE
    ]

    for c in Cliente.objects.filter(tienda=tienda):

        n = re.sub(r'[^a-z0-9]+', ' ', norm(c.nombre)).strip()

        if not n:
            continue

        nombres = [
            x for x in n.split()
            if len(x) >= 3 and x not in NO_NOMBRE
        ]

        if f' {n} ' in t:
            exactos.append((len(n), c))

        elif any(f' {x} ' in t for x in nombres):
            parciales.append(c)

        else:
            puntuacion = max(
                (
                    SequenceMatcher(None, palabra, nombre).ratio()
                    for palabra in palabras
                    for nombre in nombres
                    if len(nombre) >= 4
                ),
                default=0
            )

            if puntuacion >= 0.85:
                similares.append(c)

    if exactos:
        mayor = max(x[0] for x in exactos)
        return [c for ln, c in exactos if ln == mayor]

    if parciales:
        return parciales

    return similares

def varios(clientes):
    return resp('Encontré varios clientes: ' + ', '.join(c.nombre for c in clientes) + '. Dime el nombre completo.')


def rango(t):
    hoy = timezone.localdate()
    if 'ayer' in t:
        return hoy - timedelta(days=1), hoy - timedelta(days=1), 'ayer'
    if 'semana' in t:
        return hoy - timedelta(days=hoy.weekday()), hoy, 'esta semana'
    if re.search(r'\bmes\b', t):
        return hoy.replace(day=1), hoy, 'este mes'
    return hoy, hoy, 'hoy'


# ---------------- CONSULTAS (RF-18) ----------------
def deudores(tienda):
    return sorted([c for c in Cliente.objects.filter(tienda=tienda) if c.saldo > 0], key=lambda c: -c.saldo)


def consulta(tienda, t):
    desde, hasta, nombre = rango(t)
    if re.search(r'deb|fiad|deud|saldo|pendiente', t):
        cl = buscar_clientes(tienda, t)
        if len(cl) > 1:
            return resp(varios(cl)['texto'])
        if cl:
            c = cl[0]
            pend = [f for f in c.fiados.order_by('fecha', 'pk') if f.saldo > 0]
            if not pend:
                return resp(f'{c.nombre} no tiene deuda pendiente.')
            lineas = [f'• {f.fecha:%d/%m/%Y}: {m(f.saldo)} de {m(f.monto)}' + (' (vencido)' if f.vencido else '') for f in pend]
            return resp(f'{c.nombre} debe {m(c.saldo)} en total:\n' + '\n'.join(lineas))
        x = re.search(r'(?:debe|debo|deuda de|saldo de|fiado de)\s+(?:el |la |don |dona )?([a-z]{3,}(?: [a-z]{3,})?)', t)
        if x and not set(x.group(1).split()) & NO_NOMBRE:
            return resp(f'No encontré un cliente llamado «{x.group(1)}».', [reverse('nuevo', args=['cliente']), 'Registrar cliente'])
        lista = deudores(tienda)
        if not lista:
            return resp('Nadie te debe nada por ahora. 🎉')
        return resp(f'Fiados pendientes: {m(servicios.deuda_total(tienda))}\n' + '\n'.join(f'• {c.nombre}: {m(c.saldo)}' for c in lista[:8]))
    r = servicios.resumen_periodo(tienda, desde, hasta)
    if 'transfer' in t:
        return resp(f'Transferencias recibidas {nombre}: {m(r["transferencias"])} (incluye abonos de fiados).\nRecuerda que se registran a mano y no se verifican con el banco.')
    if 'gasto' in t:
        extra = ''.join(f'\n• {c["nombre"]}: {m(c["total"])}' for c in r['categorias'])
        return resp(f'Gastos {nombre}: {m(r["gastos"])}' + extra)
    if 'venta' in t:
        texto = f'Ventas {nombre}: {m(r["ventas"])}'
        if desde == hasta:
            d = servicios.totales_dia(tienda, desde)
            texto += f'\n• Efectivo: {m(d["efectivo"])}\n• Transferencias de ventas: {m(d["transferencias_venta"])}'
        return resp(texto)
    if re.search(r'resumen|como voy|balance|total|cuanto', t):
        return resp(f'Resumen {nombre}:\n• Ventas: {m(r["ventas"])}\n• Gastos: {m(r["gastos"])}\n• Transferencias: {m(r["transferencias"])}\n'
                    f'• Fiados pendientes: {m(servicios.deuda_total(tienda))}\n(Ventas − gastos no es ganancia neta.)')
    return resp(AYUDA)


# ---------------- REGISTROS CON CONFIRMACIÓN (RF-19, RF-20) ----------------
def pedir_monto(ejemplo):
    return resp(f'Me falta el monto. Ejemplo: «{ejemplo}».')


def preparar_gasto(t, fecha):
    monto = extraer_monto(t)
    if not monto or monto <= 0:
        return pedir_monto('registra un gasto de 10 en servicios'), None
    cat = next((k for k, claves in CATEGORIA_CLAVES.items() if any(c in t for c in claves)), 'otros')
    x = re.search(r'\b(?:en|por|para|de)\s+(?!\d)([a-z ]+)$', t)
    desc = (x.group(1).strip()[:80] if x else '')
    nombre_cat = dict(CATEGORIAS)[cat]
    p = {'tipo': 'gasto', 'monto': str(monto), 'categoria': cat, 'descripcion': desc, 'fecha': fecha.isoformat()}
    return resp(f'Voy a registrar un gasto de {m(monto)} en {nombre_cat}' + (f' ({desc})' if desc else '') + f', fecha {fecha:%d/%m/%Y}. ¿Confirmas?', confirmar=True), p


def preparar_transferencia_venta(t, fecha):
    monto = extraer_monto(t)
    if not monto or monto <= 0:
        return pedir_monto('transferencia de 12 por una venta'), None
    x = re.search(r'\b(?:por|de|concepto)\s+(?!\d)([a-z ]+)$', t)
    concepto = (x.group(1).strip()[:100] if x else '') or 'Cobro de venta'
    p = {'tipo': 'transferencia', 'monto': str(monto), 'concepto': concepto.capitalize(), 'fecha': fecha.isoformat()}
    return resp(f'Voy a registrar una transferencia de {m(monto)} como cobro de venta ({concepto}), fecha {fecha:%d/%m/%Y}. ¿Confirmas?', confirmar=True), p


def preparar_abono(tienda, t, fecha, metodo):
    cl = buscar_clientes(tienda, t)
    if len(cl) > 1:
        return varios(cl), None
    if not cl:
        return resp('¿De qué cliente es el abono? Ejemplo: «Juan Pérez abonó $10».'), None
    c, monto = cl[0], extraer_monto(t)
    if not monto or monto <= 0:
        return pedir_monto(f'{c.nombre} abonó $10'), None
    saldo = c.saldo
    if saldo <= 0:
        return resp(f'{c.nombre} no tiene deuda pendiente. Si fue un cobro de venta, di «transferencia de {monto} por una venta».'), None
    if monto > saldo:
        return resp(f'{c.nombre} debe {m(saldo)} y el abono es de {m(monto)}. No puedo dejar saldos negativos; corrige el monto.'), None
    p = {'tipo': 'abono', 'cliente_id': c.pk, 'monto': str(monto), 'metodo': metodo, 'fecha': fecha.isoformat()}
    return resp(f'Voy a registrar un abono de {m(monto)} de {c.nombre} ({metodo}). Su deuda pasará de {m(saldo)} a {m(saldo - monto)}. ¿Confirmas?', confirmar=True), p


def preparar_fiado(tienda, t, fecha):
    cl = buscar_clientes(tienda, t)
    if len(cl) > 1:
        return varios(cl), None
    if not cl:  # RF-20: no se crean datos incompletos
        return resp('No encontré a ese cliente. Para fiar, primero regístralo con sus datos.', [reverse('nuevo', args=['cliente']), 'Registrar cliente nuevo']), None
    c, monto = cl[0], extraer_monto(t)
    if not monto or monto <= 0:
        return pedir_monto(f'fiado de 20 para {c.nombre}'), None
    venc, x = None, re.search(r'vence(?:n)?\s+en\s+(\d+)\s+dias?', t)
    if x:
        venc = fecha + timedelta(days=int(x.group(1)))
    p = {'tipo': 'fiado', 'cliente_id': c.pk, 'monto': str(monto), 'fecha': fecha.isoformat(), 'vencimiento': venc.isoformat() if venc else ''}
    return resp(f'Voy a registrar un fiado de {m(monto)} para {c.nombre}' + (f' (vence {venc:%d/%m/%Y})' if venc else '') +
                f'. Su deuda pasará de {m(c.saldo)} a {m(c.saldo + monto)}. ¿Confirmas?', confirmar=True), p


def ejecutar(tienda, p):
    fecha, monto, tipo = date.fromisoformat(p['fecha']), Decimal(p['monto']), p['tipo']
    if tipo in ('gasto', 'transferencia') and servicios.dia_cerrado(tienda, fecha):
        raise ValidationError(CERRADO)
    with transaction.atomic():
        if tipo == 'gasto':
            Gasto.objects.create(tienda=tienda, monto=monto, fecha=fecha, categoria=p['categoria'], descripcion=p['descripcion'])
            return 'Listo ✅ Gasto registrado.'
        if tipo == 'transferencia':
            Transferencia.objects.create(tienda=tienda, monto=monto, fecha=fecha, concepto=p['concepto'], tipo='venta')
            return 'Listo ✅ Transferencia registrada. Recuerda que no se verifica con el banco.'
        c = Cliente.objects.get(pk=p['cliente_id'], tienda=tienda)
        if tipo == 'fiado':
            Fiado.objects.create(cliente=c, monto=monto, fecha=fecha, descripcion='Registrado con el asistente',
                                 vencimiento=date.fromisoformat(p['vencimiento']) if p['vencimiento'] else None)
            return f'Listo ✅ Fiado registrado. {c.nombre} debe ahora {m(c.saldo)}.'
        if monto > c.saldo:
            raise ValidationError(f'{c.nombre} debe solo {m(c.saldo)}.')
        restante = monto  # el abono se aplica primero al fiado más antiguo
        for f in [f for f in c.fiados.order_by('fecha', 'pk') if f.saldo > 0]:
            parte = min(restante, f.saldo)
            servicios.registrar_abono(tienda, f.pk, parte, p['metodo'], fecha)
            restante -= parte
            if restante <= 0:
                break
        return f'Listo ✅ Abono registrado. {c.nombre} debe ahora {m(c.saldo)}.'


def confirmar(tienda, estado):
    p, estado['pendiente'] = estado.get('pendiente'), None
    if not p:
        return resp('No hay nada pendiente por confirmar.')
    try:
        return resp(ejecutar(tienda, p))
    except (ValidationError, Cliente.DoesNotExist) as e:
        return resp('No pude guardarlo: ' + (e.messages[0] if hasattr(e, 'messages') else 'el cliente ya no existe.'))


def cancelar(estado):
    estado['pendiente'] = None
    return resp('Operación cancelada. No se guardó nada.')


# ---------------- PROMOCIONES ORIENTATIVAS (RF-21) ----------------
def descuento_sugerido(dias):
    return Decimal('0.30') if dias <= 2 else Decimal('0.20') if dias <= 5 else Decimal('0.15') if dias <= 10 else Decimal('0.10')


def promo(t, estado):
    estado['promo'] = None
    dias = None
    if re.search(r'\bhoy\b', t):
        dias = 0
    elif 'manana' in t:
        dias = 1
    elif 'semana' in t:
        dias = 7
    x = re.search(r'(\d+)\s+dias?', t)
    if x:
        dias = int(x.group(1))
    t2 = re.sub(r'(?:en|dentro de)\s+\d+\s+dias?', '', t)
    px = re.search(r'(?:\$|\ba\s)\s*\$?\s*(' + NUM + ')', t2)
    precio = dec(px.group(1)) if px else None
    cx = re.search(r'(?<![\d$.,])(\d+)\s+([a-z ]+?)(?=\s+(?:a|que|con|vencen|vence|cuesta|cada|precio)\b|\s*$)', t2)
    cantidad, producto = (int(cx.group(1)), cx.group(2).strip()) if cx else (None, 'el producto')
    if precio is None or dias is None:
        return resp('Para sugerir una promoción necesito el producto, cuántos tienes, su precio normal y en cuántos días vence.\n'
                    'Ejemplo: «promoción para 20 yogures a 1,50 que vencen en 3 días».')
    desc = descuento_sugerido(dias)
    nuevo = (precio * (1 - desc)).quantize(Decimal('0.01'))
    estado['promo'] = {'precio': str(precio), 'nuevo': str(nuevo), 'cantidad': cantidad, 'producto': producto}
    cuando = 'vence hoy' if dias == 0 else f'vence en {dias} día(s)'
    texto = f'Como {producto} {cuando}, te sugiero {int(desc * 100)}% de descuento: de {m(precio)} a {m(nuevo)} cada uno.'
    if cantidad:
        texto += f'\nSi vendes los {cantidad}, ingresarías {m(nuevo * cantidad)}.'
    consejo = gemini.promocion(precio, nuevo, cantidad)
    return resp(texto + '\nEs una sugerencia orientativa. Si me dices cuánto te costó cada uno, reviso que no pierdas dinero.' + ('\nConsejo de Gemini: ' + consejo if consejo else ''))


def promo_costo(t, estado):
    p, estado['promo'] = estado['promo'], None
    costo, nuevo, cant = extraer_monto(t), Decimal(p['nuevo']), p['cantidad']
    if costo is None:
        return resp('No entendí el costo. Dime por ejemplo «me costó 0,80».')
    if nuevo < costo:
        piso = (costo * Decimal('1.05')).quantize(Decimal('0.01'))
        return resp(f'⚠️ A {m(nuevo)} perderías {m(costo - nuevo)} por unidad (te costó {m(costo)}). Mejor no bajes de {m(piso)} cada uno.')
    gan = nuevo - costo
    texto = f'Con precio {m(nuevo)} y costo {m(costo)} ganas {m(gan)} por unidad'
    texto += f' ({m(gan * cant)} si vendes los {cant}).' if cant else '.'
    return resp(texto + ' Eso es margen sobre este producto, no utilidad neta del negocio.')


# ---------------- ENTRADA PRINCIPAL ----------------
def procesar(tienda, texto, estado):
    """Devuelve la respuesta (dict) y deja el estado de la conversación en `estado`."""
    t = palabras_a_digitos(norm(texto)).strip()
    if estado.get('pendiente'):
        if re.fullmatch(r'(si|confirmo|confirmar|ok|dale|correcto|listo|claro|confirmado)[ .!]*', t):
            return confirmar(tienda, estado)
        if re.fullmatch(r'(no|cancelar|cancela|cancelo|nada)[ .!]*', t):
            return cancelar(estado)
        estado['pendiente'] = None  # un mensaje nuevo reemplaza lo anterior
    if estado.get('promo') and (re.search(r'cost|compr|salio|me cobraron', t) or re.fullmatch(r'\$?\s*' + NUM + r'\s*(?:dolares?|usd)?', t)):
        return promo_costo(t, estado)
    estado['promo'] = None
    if re.search(r'promo|descuento|oferta|caduc|por vencer', t) or (re.search(r'\bvencen?\b', t) and 'fiado' not in t and 'fia' not in t):
        return promo(t, estado)
    if re.search(r'^(analiza|analizar|como le fue|como va mi negocio|como me fue|recomendaciones|consejos|informe inteligente)', t) and not re.search(r'registra|anota|guarda|abono|cliente', t):
        desde, hasta, _ = rango(t)
        analisis = gemini.analizar(tienda, desde, hasta)
        if analisis:
            return resp('Análisis de Gemini:\n' + analisis)
        return resp('Gemini no está disponible. Resumen local:\n' + consulta(tienda, 'resumen ' + t)['texto'])
    registro = bool(re.search(r'\b(registra|registrar|anota|anotar|agrega|agregar|guarda|guardar|crea|crear)\b', t))
    pregunta = bool(re.search(r'\?|^(cuanto|cuantos|cuanta|quien|quienes|cual|cuales|que|dime|dame|muestra|muestrame|mostrar|ver|consulta|resumen|'
                              r'ventas|gastos|transferencias|fiados|deudas|deudores)\b|\b(de hoy|de ayer|de la semana|del mes|esta semana|este mes)\b', t))
    if pregunta and not registro:
        return consulta(tienda, t)
    fecha = timezone.localdate() - timedelta(days=1) if re.search(r'\bayer\b', t) else timezone.localdate()
    if re.search(r'transfer|transfir|deposit', t):
        if 'venta' not in t and buscar_clientes(tienda, t):
            r, p = preparar_abono(tienda, t, fecha, 'transferencia')
        else:
            r, p = preparar_transferencia_venta(t, fecha)
    elif re.search(r'\babon|me pago|me pagaron|\bpago de\b', t):
        r, p = preparar_abono(tienda, t, fecha, 'efectivo')
    elif re.search(r'\bfia|fiado|\bfie\b', t):
        r, p = preparar_fiado(tienda, t, fecha)
    elif re.search(r'\bgast(?:o|e|a|ado)\b|\bcompre\b|\bpague\b', t):
        r, p = preparar_gasto(t, fecha)
    else:
        return consulta(tienda, t)
    estado['pendiente'] = p
    return r
