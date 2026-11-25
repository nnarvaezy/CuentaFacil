import time
from datetime import timedelta
from functools import wraps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from . import servicios, gemini
from . import asistente as motor
from .models import Tienda, Cliente, Fiado, Abono, Gasto, Transferencia, CierreDiario
from .forms import (RegistroForm, LoginForm, PinForm, PinConfigForm,
                    ClienteForm, FiadoForm, AbonoForm, GastoForm, TransferenciaForm, TransferenciaEditForm, EfectivoForm)


def con_tienda(vista):
    """El usuario debe tener tienda; un admin sin tienda va al panel de Django."""
    @wraps(vista)
    def envuelta(request, *a, **k):
        if not hasattr(request.user, 'tienda'):
            if request.user.is_staff:
                return redirect('admin:index')
            raise Http404('No existe tienda para este usuario')
        request.tienda = request.user.tienda
        return vista(request, *a, **k)
    return envuelta


def desbloquear(request):
    request.session['desbloqueado'] = True
    request.session['ultima'] = time.time()


class Login(LoginView):
    template_name = 'login.html'
    authentication_form = LoginForm

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            tienda = getattr(request.user, 'tienda', None)

            if tienda:
                if not tienda.pin_hash:
                    return redirect('pin_config')

                request.session['desbloqueado'] = False
                return redirect('pin')

            return redirect('inicio')

        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        resp = super().form_valid(form)

        desbloquear(self.request)

        if form.cleaned_data.get('recordarme'):
            self.request.session.set_expiry(60 * 60 * 24 * 30)
        else:
            self.request.session.set_expiry(0)

        tienda = getattr(self.request.user, 'tienda', None)

        if tienda and not tienda.pin_hash:
            return redirect('pin_config')

        return resp

def bienvenida(request):
    if request.user.is_authenticated:

        tienda = getattr(request.user, 'tienda', None)

        if tienda:
            if not tienda.pin_hash:
                return redirect('pin_config')

            request.session['desbloqueado'] = False
            return redirect('pin')

        return redirect('inicio')

    return render(request, 'bienvenida.html')

def registro(request):
    form = RegistroForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save()
            c = form.cleaned_data
            Tienda.objects.create(propietario=user, nombre=c['nombre_tienda'],
                                  telefono=c['telefono'], cedula=c['cedula'], direccion=c['direccion'])
        login(request, user)
        desbloquear(request)
        return redirect('pin_config')
    return render(request, 'registro.html', {'form': form})


@login_required
@con_tienda
def pin_config(request):
    form = PinConfigForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        t = request.tienda
        t.pin_hash = make_password(form.cleaned_data['pin'])
        t.pin_intentos, t.pin_bloqueo_hasta = 0, None
        t.save()
        messages.success(request, 'PIN guardado. Se pedirá tras 5 minutos de inactividad.')
        return redirect('inicio')
    return render(request, 'pin.html', {'form': form, 'titulo': 'Crea tu PIN', 'config': True})


@login_required
@con_tienda
def pin(request):
    t = request.tienda
    if not t.pin_hash:
        return redirect('pin_config')
    ahora = timezone.now()
    bloqueado = bool(t.pin_bloqueo_hasta and t.pin_bloqueo_hasta > ahora)
    form = PinForm(request.POST or None)
    if bloqueado:
        form.add_error(None, 'Demasiados intentos. Espera unos minutos o ingresa con tu contraseña.')
    elif request.method == 'POST' and form.is_valid():
        if check_password(form.cleaned_data['pin'], t.pin_hash):
            t.pin_intentos, t.pin_bloqueo_hasta = 0, None
            t.save()
            desbloquear(request)
            return redirect('inicio')
        t.pin_intentos += 1
        if t.pin_intentos >= settings.PIN_MAX_INTENTOS:
            t.pin_bloqueo_hasta = ahora + timedelta(minutes=settings.PIN_BLOQUEO_MINUTOS)
            t.pin_intentos = 0
        t.save()
        form.add_error('pin', 'PIN incorrecto.')
    return render(request, 'pin.html', {'form': form, 'titulo': 'Ingresa tu PIN', 'config': False})


@login_required
@con_tienda
def inicio(request):
    t = request.tienda
    ctx = servicios.totales_dia(t, timezone.localdate())
    ctx.update(tienda=t, deuda=servicios.deuda_total(t),
               abonos=servicios.suma(Abono.objects.filter(fiado__cliente__tienda=t, fecha=timezone.localdate())))
    ctx['saldo_operativo'] = ctx['ventas'] - ctx['gastos']
    return render(request, 'inicio.html', ctx)


@login_required
@con_tienda
def clientes(request):
    q, f = request.GET.get('q', '').strip(), request.GET.get('f', 'todos')
    filas = [{'c': c, 'saldo': c.saldo} for c in Cliente.objects.filter(tienda=request.tienda).order_by('nombre')
             if not q or motor.norm(q) in motor.norm(c.nombre)]
    n_con, n_sin = sum(1 for x in filas if x['saldo'] > 0), sum(1 for x in filas if x['saldo'] <= 0)
    if f == 'con':
        filas = [x for x in filas if x['saldo'] > 0]
    elif f == 'sin':
        filas = [x for x in filas if x['saldo'] <= 0]
    else:
        f = 'todos'
    return render(request, 'clientes.html', {'filas': filas, 'q': q, 'f': f, 'n_todos': n_con + n_sin, 'n_con': n_con, 'n_sin': n_sin})


@login_required
@con_tienda
def cliente_detalle(request, pk):
    c = get_object_or_404(Cliente, pk=pk, tienda=request.tienda)
    return render(request, 'cliente_detalle.html', {'c': c, 'fiados': c.fiados.prefetch_related('abonos').order_by('-fecha', '-pk')})


@login_required
@con_tienda
def deudas(request):
    fiados = Fiado.objects.filter(cliente__tienda=request.tienda).select_related('cliente').order_by('-fecha', '-pk')
    return render(request, 'deudas.html', {'fiados': sorted(fiados, key=lambda f: f.saldo <= 0)})


TITULOS = {'cliente': 'Nuevo cliente', 'fiado': 'Registrar fiado', 'abono': 'Registrar abono',
           'gasto': 'Registrar gasto', 'transferencia': 'Registrar transferencia'}
FORMS = {'cliente': ClienteForm, 'fiado': FiadoForm, 'abono': AbonoForm, 'gasto': GastoForm, 'transferencia': TransferenciaForm}
DESTINO = {'cliente': 'clientes', 'fiado': 'deudas', 'abono': 'deudas', 'gasto': 'movimientos', 'transferencia': 'movimientos'}
SUBTITULOS = {'cliente': 'Guarda los datos de tu cliente.', 'fiado': 'Registra una nueva venta a crédito para un cliente.',
              'abono': 'Registra un pago parcial o total de un cliente.', 'gasto': 'Registra un gasto de tu tienda.',
              'transferencia': 'Registra un ingreso recibido por transferencia.'}
AVISO = 'Las transferencias se registran manualmente: CuentaFácil no las verifica con el banco.'
CERRADO = 'Ese día está cerrado. Reabre el cierre en Ventas para registrar o corregir.'


def pendientes(t):
    ids = [f.pk for f in Fiado.objects.filter(cliente__tienda=t) if f.saldo > 0]
    return Fiado.objects.filter(pk__in=ids).select_related('cliente')


@login_required
@con_tienda
def nuevo(request, tipo):
    if tipo not in FORMS:
        raise Http404()
    t = request.tienda
    form = FORMS[tipo](request.POST or None)
    if tipo == 'fiado':
        form.fields['cliente'].queryset = Cliente.objects.filter(tienda=t).order_by('nombre')
        form.fields['cliente'].empty_label = 'Selecciona un cliente'
    if tipo in ('abono', 'transferencia'):
        form.fields['fiado'].queryset = pendientes(t)
        form.fields['fiado'].label = 'Fiado pendiente' if tipo == 'abono' else 'Fiado que se abona (solo si es abono)'
        form.fields['fiado'].empty_label = 'Selecciona un fiado pendiente'
        form.fields['fiado'].label_from_instance = lambda f: f'{f.cliente.nombre} · pendiente {motor.m(f.saldo)} · {f.fecha:%d/%m/%Y}'
    ctx = {'form': form, 'titulo': TITULOS[tipo], 'subtitulo': SUBTITULOS[tipo], 'boton': 'Guardar ' + tipo, 'volver': reverse(DESTINO[tipo]),
           'aviso': AVISO if tipo == 'transferencia' else ''}
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            with transaction.atomic():
                if tipo == 'abono':
                    servicios.registrar_abono(t, d['fiado'].pk, d['monto'], d['metodo'], d['fecha'])
                elif tipo == 'transferencia' and d['tipo'] == 'abono':
                    servicios.registrar_abono(t, d['fiado'].pk, d['monto'], 'transferencia', d['fecha'], d['concepto'])
                else:
                    if tipo in ('gasto', 'transferencia') and servicios.dia_cerrado(t, d['fecha']):
                        raise ValidationError(CERRADO)
                    obj = form.save(commit=False)
                    if tipo != 'fiado':
                        obj.tienda = t
                    obj.save()
        except ValidationError as e:
            form.add_error(None, e.messages[0])
            return render(request, 'form.html', ctx)
        messages.success(request, 'Guardado correctamente.')
        return redirect(DESTINO[tipo])
    return render(request, 'form.html', ctx)


@login_required
@con_tienda
def editar(request, tipo, pk):
    t = request.tienda
    if tipo == 'gasto':
        obj, F = get_object_or_404(Gasto, pk=pk, tienda=t), GastoForm
    elif tipo == 'transferencia':  # las de abono se corrigen desde el abono
        obj, F = get_object_or_404(Transferencia, pk=pk, tienda=t, tipo='venta'), TransferenciaEditForm
    else:
        raise Http404()
    if servicios.dia_cerrado(t, obj.fecha):
        messages.error(request, CERRADO)
        return redirect('movimientos')
    form = F(request.POST or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        if servicios.dia_cerrado(t, form.cleaned_data['fecha']):
            form.add_error('fecha', CERRADO)
        else:
            form.save()
            messages.success(request, 'Registro corregido.')
            return redirect('movimientos')
    return render(request, 'form.html', {'form': form, 'titulo': 'Corregir ' + tipo, 'boton': 'Guardar cambios',
                                         'subtitulo': 'Corrige los datos del registro.', 'volver': reverse('movimientos'),
                                         'aviso': AVISO if tipo == 'transferencia' else ''})


@login_required
@con_tienda
def movimientos(request):
    t, hoy = request.tienda, timezone.localdate()
    tab = 'gastos' if request.GET.get('t') == 'gastos' else 'transferencias'
    mes = {'tienda': t, 'fecha__gte': hoy.replace(day=1)}
    if tab == 'gastos':
        items, total = Gasto.objects.filter(tienda=t).order_by('-fecha', '-pk')[:60], servicios.suma(Gasto.objects.filter(**mes))
    else:
        items, total = Transferencia.objects.filter(tienda=t).order_by('-fecha', '-pk')[:60], servicios.suma(Transferencia.objects.filter(**mes))
    cerrados = set(CierreDiario.objects.filter(tienda=t, cerrado=True).values_list('fecha', flat=True))
    return render(request, 'movimientos.html', {'tab': tab, 'items': items, 'total': total, 'cerrados': cerrados, 'aviso': AVISO})


@login_required
@con_tienda
def ventas_dia(request):
    t, hoy = request.tienda, timezone.localdate()
    fecha = min(parse_date(request.POST.get('fecha') or request.GET.get('fecha') or '') or hoy, hoy)
    cierre = CierreDiario.objects.filter(tienda=t, fecha=fecha).first() or CierreDiario(tienda=t, fecha=fecha)
    form = EfectivoForm(initial={'ventas_efectivo': cierre.ventas_efectivo})
    if request.method == 'POST':
        accion = request.POST.get('accion')
        volver = f"{reverse('ventas_dia')}?fecha={fecha:%Y-%m-%d}"
        if accion == 'reabrir':
            servicios.reabrir_dia(t, fecha)
            messages.success(request, 'Día reabierto. Ya puedes corregir.')
            return redirect(volver)
        if cierre.cerrado:
            messages.error(request, 'El día ya está cerrado.')
            return redirect(volver)
        form = EfectivoForm(request.POST)
        if form.is_valid():
            cierre.ventas_efectivo = form.cleaned_data['ventas_efectivo']
            cierre.save()
            if accion == 'cerrar':
                servicios.cerrar_dia(t, fecha)
                messages.success(request, 'Día cerrado correctamente.')
            else:
                messages.success(request, 'Ventas guardadas.')
            return redirect(volver)
    ultimo = CierreDiario.objects.filter(tienda=t, cerrado=True).exclude(pk=cierre.pk).order_by('-fecha').first()
    ctx = servicios.totales_dia(t, fecha)
    ctx['saldo_operativo'] = ctx['ventas'] - ctx['gastos']
    ctx.update(form=form, fecha=fecha, hoy=hoy, cierre=cierre, ultimo=ultimo)
    return render(request, 'ventas_dia.html', ctx)


@login_required
@con_tienda
def reportes(request):
    t, hoy = request.tienda, timezone.localdate()
    p = request.POST.get('p', 'semana') if request.method == 'POST' else request.GET.get('p', 'semana')
    if p == 'dia':
        desde = hoy
    elif p == 'mes':
        desde = hoy.replace(day=1)
    else:
        p, desde = 'semana', hoy - timedelta(days=hoy.weekday())
    r = servicios.resumen_periodo(t, desde, hoy)
    r.update(p=p, desde=desde, hasta=hoy, deuda=servicios.deuda_total(t), saldo_operativo=0)
    r['saldo_operativo'] = r['ventas'] - r['gastos']
    if request.method == 'POST' and request.POST.get('accion') == 'analizar':
        r['analisis_ia'] = gemini.analizar(t, desde, hoy)
        r['ia_error'] = not r['analisis_ia']
    return render(request, 'reportes.html', r)


@login_required
@con_tienda
def asistente(request):
    """Chat de texto/voz. Las respuestas son siempre texto escrito (RF-22). Lo que registra requiere confirmación."""
    estado = request.session.get('asistente') or {'chat': [], 'pendiente': None, 'promo': None}
    if request.method == 'POST':
        accion, texto = request.POST.get('accion'), (request.POST.get('texto') or '').strip()[:300]
        if accion == 'confirmar':
            estado['chat'].append({'rol': 'u', 'texto': 'Confirmo'})
            r = motor.confirmar(request.tienda, estado)
        elif accion == 'cancelar':
            estado['chat'].append({'rol': 'u', 'texto': 'Cancelar'})
            r = motor.cancelar(estado)
        elif texto:
            estado['chat'].append({'rol': 'u', 'texto': texto})
            r = motor.procesar(request.tienda, texto, estado)
        else:
            return redirect('asistente')
        estado['chat'] = (estado['chat'] + [{'rol': 'a', **r}])[-40:]
        request.session['asistente'] = estado
        return redirect('asistente')
    return render(request, 'asistente.html', {'chat': estado['chat'], 'pendiente': bool(estado.get('pendiente'))})
