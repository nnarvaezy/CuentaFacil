import time
from datetime import timedelta
from core import servicios
from decimal import Decimal
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import *

CLAVE = 'Clave-Segura-77'


class Base(TestCase):
    def reg(self, mail='ana@x.com', tienda='Tienda A'):
        return self.client.post(reverse('registro'), {'first_name': 'Ana', 'email': mail, 'nombre_tienda': tienda,
                                                      'password1': CLAVE, 'password2': CLAVE})

    def cliente_fiado(self, monto='25.00'):
        self.client.post(reverse('nuevo', args=['cliente']), {'nombre': 'Juan', 'telefono': '099'})
        c = Cliente.objects.get()
        self.client.post(reverse('nuevo', args=['fiado']), {'cliente': c.pk, 'monto': monto, 'fecha': timezone.localdate()})
        return c, Fiado.objects.get()

    def poner_pin(self, pin='12345'):
        return self.client.post(reverse('pin_config'), {'pin': pin, 'pin2': pin})


class Cuenta(Base):
    def test_registro_y_perfil(self):
        r = self.reg(); self.assertRedirects(r, reverse('pin_config'))
        self.assertEqual(self.client.get(reverse('inicio')).status_code, 200)
        self.assertEqual(Tienda.objects.get().nombre, 'Tienda A')

    def test_login_con_correo(self):
        self.reg(); self.client.logout()
        r = self.client.post(reverse('login'), {'username': 'ANA@x.com', 'password': CLAVE})
        self.assertRedirects(r, reverse('inicio'), fetch_redirect_response=False)

    def test_correo_duplicado(self):
        self.reg(); self.client.logout()
        self.assertEqual(self.reg(tienda='B').status_code, 200); self.assertEqual(User.objects.count(), 1)

    def test_cedula_invalida(self):
        r = self.client.post(reverse('registro'), {'first_name': 'A', 'email': 'a@a.com', 'nombre_tienda': 'T', 'cedula': '123',
                                                   'password1': CLAVE, 'password2': CLAVE})
        self.assertEqual(r.status_code, 200); self.assertEqual(User.objects.count(), 0)

    def test_admin_sin_tienda_va_al_admin(self):
        User.objects.create_superuser('adm', 'a@a.com', 'x'); self.client.login(username='adm', password='x')
        self.assertRedirects(self.client.get(reverse('inicio')), reverse('admin:index'), fetch_redirect_response=False)

    def test_sin_login_redirige(self):
        for n in ('inicio', 'clientes', 'deudas', 'pin'):
            self.assertEqual(self.client.get(reverse(n)).status_code, 302)

    def test_aislamiento(self):
        self.reg(); self.client.post(reverse('nuevo', args=['cliente']), {'nombre': 'Secreto'})
        pk = Cliente.objects.get().pk; self.client.logout(); self.reg('b@x.com', 'B')
        self.assertNotContains(self.client.get(reverse('clientes')), 'Secreto')
        self.assertEqual(self.client.get(reverse('cliente_detalle', args=[pk])).status_code, 404)


class Pin(Base):
    def test_pin_guardado_con_hash(self):
        self.reg(); self.poner_pin('12345')
        h = Tienda.objects.get().pin_hash; self.assertTrue(h and '12345' not in h)

    def test_pin_debe_ser_5_digitos(self):
        self.reg(); self.poner_pin('12ab5'); self.assertEqual(Tienda.objects.get().pin_hash, '')

    def test_bloqueo_y_desbloqueo(self):
        self.reg(); self.poner_pin('12345')
        s = self.client.session; s['desbloqueado'] = False; s.save()
        self.assertRedirects(self.client.get(reverse('inicio')), reverse('pin'), fetch_redirect_response=False)
        self.client.post(reverse('pin'), {'pin': '00000'})
        self.assertRedirects(self.client.get(reverse('inicio')), reverse('pin'), fetch_redirect_response=False)
        self.assertRedirects(self.client.post(reverse('pin'), {'pin': '12345'}), reverse('inicio'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('inicio')).status_code, 200)

    def test_bloqueo_por_inactividad(self):
        self.reg(); self.poner_pin()
        s = self.client.session; s['ultima'] = time.time() - 3600; s.save()
        self.assertRedirects(self.client.get(reverse('clientes')), reverse('pin'), fetch_redirect_response=False)

    def test_limite_de_intentos(self):
        self.reg(); self.poner_pin('12345')
        s = self.client.session; s['desbloqueado'] = False; s.save()
        for _ in range(5): self.client.post(reverse('pin'), {'pin': '99999'})
        self.assertIsNotNone(Tienda.objects.get().pin_bloqueo_hasta)
        self.client.post(reverse('pin'), {'pin': '12345'})  # el correcto tampoco entra mientras dura el bloqueo
        self.assertRedirects(self.client.get(reverse('inicio')), reverse('pin'), fetch_redirect_response=False)

    def test_no_se_puede_cambiar_pin_bloqueado(self):
        self.reg(); self.poner_pin('12345')
        s = self.client.session; s['desbloqueado'] = False; s.save()
        self.assertRedirects(self.client.get(reverse('pin_config')), reverse('pin'), fetch_redirect_response=False)


class Fiados(Base):
    def test_fiado_abono_y_estado(self):
        self.reg(); c, f = self.cliente_fiado('25.00')
        self.assertEqual((f.saldo, f.estado), (Decimal('25.00'), 'Pendiente'))
        self.client.post(reverse('nuevo', args=['abono']), {'fiado': f.pk, 'monto': '10', 'metodo': 'efectivo', 'fecha': timezone.localdate()})
        self.assertEqual(Fiado.objects.get().saldo, Decimal('15.00'))
        self.client.post(reverse('nuevo', args=['abono']), {'fiado': f.pk, 'monto': '99', 'metodo': 'efectivo', 'fecha': timezone.localdate()})
        self.assertEqual(Abono.objects.count(), 1)
        self.client.post(reverse('nuevo', args=['abono']), {'fiado': f.pk, 'monto': '15', 'metodo': 'transferencia', 'fecha': timezone.localdate()})
        self.assertEqual(Fiado.objects.get().estado, 'Pagado')
        self.assertEqual(Cliente.objects.get().saldo, Decimal('0'))

    def test_pagado_no_aparece_para_abonar(self):
        self.reg(); c, f = self.cliente_fiado('5')
        self.client.post(reverse('nuevo', args=['abono']), {'fiado': f.pk, 'monto': '5', 'metodo': 'efectivo', 'fecha': timezone.localdate()})
        self.assertNotContains(self.client.get(reverse('nuevo', args=['abono'])), f'value="{f.pk}"')

    def test_vencimiento_anterior_rechazado(self):
        self.reg(); self.client.post(reverse('nuevo', args=['cliente']), {'nombre': 'J'}); c = Cliente.objects.get()
        hoy = timezone.localdate()
        self.client.post(reverse('nuevo', args=['fiado']), {'cliente': c.pk, 'monto': '5', 'fecha': hoy, 'vencimiento': hoy - timedelta(days=3)})
        self.assertEqual(Fiado.objects.count(), 0)

    def test_fiado_vencido(self):
        self.reg(); self.client.post(reverse('nuevo', args=['cliente']), {'nombre': 'J'}); c = Cliente.objects.get()
        hoy = timezone.localdate()
        self.client.post(reverse('nuevo', args=['fiado']), {'cliente': c.pk, 'monto': '5', 'fecha': hoy - timedelta(days=10), 'vencimiento': hoy - timedelta(days=2)})
        self.assertTrue(Fiado.objects.get().vencido)

    def test_detalle_y_busqueda(self):
        self.reg(); c, f = self.cliente_fiado()
        self.assertContains(self.client.get(reverse('cliente_detalle', args=[c.pk])), '25,00')
        self.assertContains(self.client.get(reverse('clientes') + '?q=jua'), 'Juan')
        self.assertNotContains(self.client.get(reverse('clientes') + '?q=zzz'), 'Juan')

    def test_tipo_invalido(self):
        self.reg(); self.assertEqual(self.client.get('/nuevo/hack/').status_code, 404)


class Etapa3(Base):
    def setUp(self):
        self.hoy = timezone.localdate()

    def gasto(self, monto='10', fecha=None, cat='servicios'):
        return self.client.post(reverse('nuevo', args=['gasto']), {'monto': monto, 'fecha': fecha or self.hoy, 'categoria': cat, 'descripcion': 'luz'})

    def transf(self, monto='45', tipo='venta', **extra):
        return self.client.post(reverse('nuevo', args=['transferencia']), {'tipo': tipo, 'monto': monto, 'fecha': self.hoy, 'concepto': 'Venta del día', **extra})

    def cierre(self, accion='cerrar', efectivo='80'):
        return self.client.post(reverse('ventas_dia'), {'accion': accion, 'ventas_efectivo': efectivo, 'fecha': self.hoy})

    def test_gasto_categoria_y_correccion(self):
        self.reg(); self.gasto('10'); g = Gasto.objects.get(); self.assertEqual(g.categoria, 'servicios')
        self.client.post(reverse('editar', args=['gasto', g.pk]), {'monto': '12', 'fecha': self.hoy, 'categoria': 'otros', 'descripcion': 'x'})
        self.assertEqual(Gasto.objects.get().monto, Decimal('12'))

    def test_montos_y_fechas_invalidos(self):
        self.reg()
        for m in ('0', '-5'): self.gasto(m)
        self.gasto('5', fecha=self.hoy + timedelta(days=2))
        self.assertEqual(Gasto.objects.count(), 0)

    def test_transferencia_de_venta(self):
        self.reg(); self.transf('45')
        t = Transferencia.objects.get(); self.assertEqual((t.tipo, t.abono), ('venta', None))
        self.assertContains(self.client.get(reverse('movimientos')), 'no las verifica con el banco')

    def test_transferencia_abono_baja_saldo_y_exige_fiado(self):
        self.reg(); c, f = self.cliente_fiado('30')
        self.transf('10', 'abono'); self.assertEqual(Transferencia.objects.count(), 0)  # sin fiado: rechazada
        self.transf('10', 'abono', fiado=f.pk)
        self.assertEqual(Fiado.objects.get().saldo, Decimal('20')); self.assertEqual(Abono.objects.get().metodo, 'transferencia')
        self.transf('99', 'abono', fiado=f.pk); self.assertEqual(Abono.objects.count(), 1)

    def test_abono_por_transferencia_aparece_en_listado_sin_sumar_ventas(self):
        self.reg(); c, f = self.cliente_fiado('20')
        self.client.post(reverse('nuevo', args=['abono']), {'fiado': f.pk, 'monto': '20', 'metodo': 'transferencia', 'fecha': self.hoy})
        self.assertEqual(Transferencia.objects.get().tipo, 'abono')
        t = servicios.totales_dia(Tienda.objects.get(), self.hoy)
        self.assertEqual((t['ventas'], t['transferencias']), (Decimal('0'), Decimal('20')))

    def test_cierre_no_suma_abonos(self):
        self.reg(); c, f = self.cliente_fiado('50'); self.transf('45'); self.gasto('20')
        self.client.post(reverse('nuevo', args=['abono']), {'fiado': f.pk, 'monto': '10', 'metodo': 'transferencia', 'fecha': self.hoy})
        self.cierre('cerrar', '80')
        c = CierreDiario.objects.get(); self.assertTrue(c.cerrado)
        self.assertEqual((c.total_ventas, c.total_gastos), (Decimal('125'), Decimal('20')))  # 80 + 45; el abono de 10 no cuenta

    def test_dia_cerrado_bloquea_y_reabre(self):
        self.reg(); self.gasto('10'); g = Gasto.objects.get(); self.cierre('cerrar')
        self.gasto('5'); self.assertEqual(Gasto.objects.count(), 1)
        self.client.post(reverse('editar', args=['gasto', g.pk]), {'monto': '99', 'fecha': self.hoy, 'categoria': 'otros', 'descripcion': ''})
        self.assertEqual(Gasto.objects.get().monto, Decimal('10'))
        self.cierre('guardar', '500'); self.assertEqual(CierreDiario.objects.get().ventas_efectivo, Decimal('80'))
        self.cierre('reabrir'); self.cierre('guardar', '90')
        self.assertEqual(CierreDiario.objects.get().ventas_efectivo, Decimal('90'))

    def test_efectivo_negativo_rechazado(self):
        self.reg(); self.cierre('guardar', '-5'); self.assertEqual(CierreDiario.objects.count(), 0)

    def test_reportes(self):
        self.reg(); self.transf('45'); self.gasto('20', cat='transporte'); self.cierre('guardar', '80')
        for p in ('dia', 'semana', 'mes'):
            r = self.client.get(reverse('reportes') + '?p=' + p)
            self.assertEqual((r.context['ventas'], r.context['gastos']), (Decimal('125'), Decimal('20')))
        self.assertEqual(r.context['categorias'][0]['nombre'], 'Transporte')

    def test_aislamiento_movimientos(self):
        self.reg(); self.gasto('10'); pk = Gasto.objects.get().pk; self.client.logout(); self.reg('b@x.com', 'B')
        self.assertEqual(self.client.get(reverse('editar', args=['gasto', pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('movimientos') + '?t=gastos').context['items'].count(), 0)

    def test_pantallas_cargan(self):
        self.reg()
        for n in ('inicio', 'clientes', 'deudas', 'movimientos', 'ventas_dia', 'reportes'):
            self.assertEqual(self.client.get(reverse(n)).status_code, 200, n)


class Asistente(Base):
    def setUp(self):
        self.hoy = timezone.localdate()
        self.reg()
        self.t = Tienda.objects.get()
        self.juan = Cliente.objects.create(tienda=self.t, nombre='Juan Pérez')
        self.maria = Cliente.objects.create(tienda=self.t, nombre='María López')
        self.f = Fiado.objects.create(cliente=self.juan, monto=Decimal('25'))
        self.e = {}

    def di(self, texto):
        from core import asistente as a
        return a.procesar(self.t, texto, self.e)

    def conf(self):
        from core import asistente as a
        return a.confirmar(self.t, self.e)

    def test_consulta_deuda_cliente(self):
        r = self.di('¿Cuánto debe Juan?')['texto']; self.assertIn('Juan Pérez debe $25,00', r)
        self.assertIn('no tiene deuda', self.di('cuánto debe María')['texto'])

    def test_consulta_quien_me_debe(self):
        r = self.di('quién me debe')['texto']; self.assertIn('Juan Pérez: $25,00', r); self.assertNotIn('María', r)

    def test_cliente_inexistente_en_consulta(self):
        r = self.di('cuánto debe Pedro')
        self.assertIn('No encontré', r['texto']); self.assertIsNotNone(r['enlace'])

    def test_consultas_de_ventas_gastos_transferencias(self):
        Gasto.objects.create(tienda=self.t, monto=Decimal('10'), fecha=self.hoy, categoria='servicios')
        Transferencia.objects.create(tienda=self.t, monto=Decimal('45'), fecha=self.hoy, concepto='v', tipo='venta')
        CierreDiario.objects.create(tienda=self.t, fecha=self.hoy, ventas_efectivo=Decimal('80'))
        self.assertIn('$125,00', self.di('ventas de hoy')['texto'])
        self.assertIn('$10,00', self.di('gastos de hoy')['texto'])
        self.assertIn('$45,00', self.di('transferencias de la semana')['texto'])
        self.assertIn('Ventas: $125,00', self.di('resumen del mes')['texto'])

    def test_gasto_pide_confirmacion_y_guarda_solo_al_confirmar(self):
        r = self.di('Registra un gasto de $10 en servicios'); self.assertTrue(r['confirmar'])
        self.assertEqual(Gasto.objects.count(), 0)  # RNF-06: aún no se guardó
        self.conf(); g = Gasto.objects.get()
        self.assertEqual((g.monto, g.categoria), (Decimal('10'), 'servicios'))

    def test_cancelar_no_guarda(self):
        self.di('gasté 15 en transporte'); self.assertEqual(self.di('no')['texto'][:9], 'Operación'); self.assertEqual(Gasto.objects.count(), 0)

    def test_confirmar_con_si(self):
        self.di('gasto de 7 en suministros'); self.assertIn('Gasto registrado', self.di('sí')['texto']); self.assertEqual(Gasto.objects.count(), 1)

    def test_numeros_en_palabras_voz(self):
        self.di('registra un gasto de diez dólares en luz'); self.conf()
        self.assertEqual(Gasto.objects.get().monto, Decimal('10'))

    def test_numeros_compuestos(self):
        for frase, esperado in (('gasto de veinte y cinco en luz', 25), ('gasto de treinta y dos en luz', 32), ('gasto de veintiocho en luz', 28)):
            self.e = {}; self.di(frase); self.conf()
        self.assertEqual(sorted(g.monto for g in Gasto.objects.all()), [25, 28, 32])

    def test_abono_baja_saldo(self):
        self.di('Juan Pérez abonó $10'); self.conf()
        self.assertEqual(Fiado.objects.get().saldo, Decimal('15')); self.assertEqual(Abono.objects.get().metodo, 'efectivo')

    def test_abono_mayor_al_saldo_rechazado(self):
        r = self.di('Juan abonó 99'); self.assertFalse(r['confirmar']); self.assertIn('saldos negativos', r['texto']); self.assertEqual(Abono.objects.count(), 0)

    def test_abono_abarca_varios_fiados(self):
        Fiado.objects.create(cliente=self.juan, monto=Decimal('10'), fecha=self.hoy)
        self.di('Juan Pérez abonó 30'); self.conf()
        self.assertEqual(self.juan.saldo, Decimal('5')); self.assertEqual(Abono.objects.count(), 2)

    def test_transferencia_de_venta(self):
        self.di('registra una transferencia de $12 por una venta'); self.conf()
        t = Transferencia.objects.get(); self.assertEqual((t.tipo, t.monto), ('venta', Decimal('12')))

    def test_transferencia_de_cliente_es_abono_y_no_suma_ventas(self):
        self.di('Juan me transfirió 10'); self.conf()
        self.assertEqual(Transferencia.objects.get().tipo, 'abono'); self.assertEqual(servicios.totales_dia(self.t, self.hoy)['ventas'], 0)

    def test_fiado_cliente_existente(self):
        self.di('registra un fiado de $20 para María López que vence en 7 días'); self.conf()
        f = Fiado.objects.get(cliente=self.maria); self.assertEqual(f.monto, Decimal('20')); self.assertEqual(f.vencimiento, self.hoy + timedelta(days=7))

    def test_fiado_cliente_no_registrado_va_al_formulario(self):
        r = self.di('fiado de 20 para Pedro'); self.assertFalse(r['confirmar'])
        self.assertEqual(r['enlace'][0], reverse('nuevo', args=['cliente'])); self.assertEqual(Fiado.objects.count(), 1)

    def test_clientes_ambiguos(self):
        Cliente.objects.create(tienda=self.t, nombre='Juan Gómez')
        self.assertIn('varios clientes', self.di('Juan abonó 5')['texto'])

    def test_falta_monto(self):
        self.assertIn('Me falta el monto', self.di('registra un gasto en servicios')['texto'])

    def test_dia_cerrado_no_permite_registrar(self):
        CierreDiario.objects.create(tienda=self.t, fecha=self.hoy, cerrado=True)
        self.di('gasto de 5 en luz'); self.assertIn('cerrado', self.conf()['texto']); self.assertEqual(Gasto.objects.count(), 0)

    def test_promocion_y_costo(self):
        r = self.di('sugiere una promoción para 20 yogures a $1,50 que vencen en 3 días')['texto']
        self.assertIn('20% de descuento', r); self.assertIn('$1,20', r); self.assertIn('$24,00', r)
        self.assertIn('perderías', self.di('me costó 1,50')['texto'])

    def test_promocion_con_margen(self):
        self.di('promoción para 10 galletas a 2 que vencen mañana'); r = self.di('me costó 1')['texto']
        self.assertIn('ganas', r)

    def test_promocion_incompleta_pregunta(self):
        self.assertIn('necesito', self.di('quiero una promoción')['texto'])

    def test_no_ve_clientes_de_otra_tienda(self):
        self.client.logout(); self.reg('b@x.com', 'B'); otra = Tienda.objects.get(nombre='B')
        from core import asistente as a
        self.assertIn('Nadie te debe', a.procesar(otra, 'quién me debe', {})['texto'])
        self.assertIn('No encontré', a.procesar(otra, 'fiado de 5 para Juan', {})['texto'])

    def test_ayuda(self):
        self.assertIn('Puedo ayudarte', self.di('hola')['texto'])

    # --- vista ---
    def post(self, **d):
        return self.client.post(reverse('asistente'), d, follow=True)

    def test_vista_flujo_completo_con_botones(self):
        self.assertEqual(self.client.get(reverse('asistente')).status_code, 200)
        r = self.post(texto='registra un gasto de 8 en luz'); self.assertContains(r, 'Confirmar'); self.assertEqual(Gasto.objects.count(), 0)
        self.post(accion='confirmar'); self.assertEqual(Gasto.objects.count(), 1)
        self.post(texto='gasto de 3 en luz'); self.post(accion='cancelar'); self.assertEqual(Gasto.objects.count(), 1)

    def test_vista_requiere_login_y_pin(self):
        self.client.logout(); self.assertEqual(self.client.get(reverse('asistente')).status_code, 302)


class Diseno(Base):
    def test_bienvenida_publica_y_redirige_si_hay_sesion(self):
        self.assertEqual(self.client.get(reverse('bienvenida')).status_code, 200)
        self.assertRedirects(self.client.get(reverse('inicio')), reverse('bienvenida') + '?next=/', fetch_redirect_response=False)
        self.reg(); self.assertRedirects(self.client.get(reverse('bienvenida')), reverse('inicio'), fetch_redirect_response=False)

    def test_recordarme(self):
        self.reg(); self.client.logout()
        self.client.post(reverse('login'), {'username': 'ana@x.com', 'password': CLAVE})
        self.assertTrue(self.client.session.get_expire_at_browser_close())
        self.client.logout()
        self.client.post(reverse('login'), {'username': 'ana@x.com', 'password': CLAVE, 'recordarme': 'on'})
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_recuperar_contrasena_por_correo(self):
        import re
        from django.core import mail
        self.reg(); self.client.logout()
        self.assertRedirects(self.client.post(reverse('recuperar'), {'email': 'ana@x.com'}), reverse('recuperar_enviado'))
        self.assertEqual(len(mail.outbox), 1)
        enlace = re.search(r'http://testserver(/recuperar/[^\s]+)', mail.outbox[0].body).group(1)
        r = self.client.get(enlace, follow=True)
        self.client.post(r.redirect_chain[-1][0], {'new_password1': 'Otra-Clave-88', 'new_password2': 'Otra-Clave-88'})
        self.assertTrue(self.client.login(username='ana@x.com', password='Otra-Clave-88'))

    def test_recuperar_con_correo_inexistente_no_revela_nada(self):
        from django.core import mail
        self.assertRedirects(self.client.post(reverse('recuperar'), {'email': 'nadie@x.com'}), reverse('recuperar_enviado')); self.assertEqual(len(mail.outbox), 0)

    def test_filtros_de_clientes(self):
        self.reg(); self.client.post(reverse('nuevo', args=['cliente']), {'nombre': 'Juan'}); self.client.post(reverse('nuevo', args=['cliente']), {'nombre': 'Ana'})
        j = Cliente.objects.get(nombre='Juan'); Fiado.objects.create(cliente=j, monto=Decimal('9'))
        r = self.client.get(reverse('clientes') + '?f=con'); self.assertContains(r, 'Juan'); self.assertNotContains(r, '>Ana<')
        r = self.client.get(reverse('clientes') + '?f=sin'); self.assertContains(r, 'Ana')
        self.assertEqual((r.context['n_todos'], r.context['n_con'], r.context['n_sin']), (2, 1, 1))

    def test_busqueda_sin_importar_tildes(self):
        self.reg(); self.client.post(reverse('nuevo', args=['cliente']), {'nombre': 'María López'})
        self.assertContains(self.client.get(reverse('clientes') + '?q=maria'), 'María López')

    def test_inicio_muestra_abonos_de_hoy_y_montos_con_dos_decimales(self):
        self.reg(); c, f = self.cliente_fiado('30')
        self.client.post(reverse('nuevo', args=['abono']), {'fiado': f.pk, 'monto': '12', 'metodo': 'efectivo', 'fecha': timezone.localdate()})
        r = self.client.get(reverse('inicio')); self.assertEqual(r.context['abonos'], Decimal('12')); self.assertContains(r, '$12,00')

    def test_formulario_abono_sin_opcion_en_blanco_y_etiquetas(self):
        self.reg(); r = self.client.get(reverse('nuevo', args=['abono']))
        self.assertContains(r, 'Método de pago'); self.assertNotContains(r, '---------</option>\n<option value="efectivo"')

    def test_pin_con_teclado_pagina(self):
        self.reg(); self.poner_pin(); r = self.client.get(reverse('pin'))
        self.assertContains(r, 'data-n="9"'); self.assertNotContains(r, 'class="nav"')

    def test_menu_y_cabecera_en_pantallas(self):
        self.reg()
        for n in ('inicio', 'clientes', 'movimientos', 'reportes', 'ventas_dia', 'asistente', 'deudas'):
            self.assertContains(self.client.get(reverse(n)), 'CuentaFácil', msg_prefix=n)


class Logo(Base):
    def test_archivos_del_logo_existen(self):
        from django.contrib.staticfiles import finders
        for f in ('logo-header.png', 'logo-banner.png', 'icono.png'):
            self.assertIsNotNone(finders.find('core/' + f), f)

    def test_logo_en_cabecera_y_bienvenida(self):
        self.assertContains(self.client.get(reverse('bienvenida')), 'core/logo-banner.png')
        self.assertContains(self.client.get(reverse('login')), 'core/logo-header.png')

    def test_boton_flotante_del_asistente(self):
        self.reg()
        for n in ('inicio', 'clientes', 'movimientos', 'reportes', 'ventas_dia', 'deudas'):
            self.assertContains(self.client.get(reverse(n)), 'class="fab"', msg_prefix=n)
        self.assertNotContains(self.client.get(reverse('asistente')), 'class="fab"')  # ya estás en el asistente
        self.poner_pin(); self.assertNotContains(self.client.get(reverse('pin')), 'class="fab"')  # ni en el bloqueo por PIN
        self.client.logout(); self.assertNotContains(self.client.get(reverse('login')), 'class="fab"')
