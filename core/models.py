from decimal import Decimal
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

MONTO = dict(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
CATEGORIAS = [('servicios', 'Servicios'), ('transporte', 'Transporte'), ('suministros', 'Suministros'), ('mercaderia', 'Mercadería'), ('otros', 'Otros')]
TIPOS_TRANSFERENCIA = [('venta', 'Cobro de una venta'), ('abono', 'Abono de un fiado')]
METODOS = [('efectivo', 'Efectivo'), ('transferencia', 'Transferencia')]


class Tienda(models.Model):
    propietario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='tienda')
    nombre = models.CharField(max_length=120)
    telefono = models.CharField(max_length=20, blank=True)
    cedula = models.CharField(max_length=10, blank=True)
    direccion = models.CharField(max_length=200, blank=True)
    # PIN de 5 dígitos: solo se guarda el hash, nunca el número (RNF-02)
    pin_hash = models.CharField(max_length=255, blank=True)
    pin_intentos = models.PositiveSmallIntegerField(default=0)
    pin_bloqueo_hasta = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.nombre


class Cliente(models.Model):
    tienda = models.ForeignKey(Tienda, on_delete=models.CASCADE, related_name='clientes')
    nombre = models.CharField(max_length=120)
    telefono = models.CharField(max_length=20, blank=True)
    referencia = models.CharField(max_length=150, blank=True)

    def __str__(self):
        return self.nombre

    @property
    def saldo(self):
        return sum((f.saldo for f in self.fiados.all()), Decimal('0'))


class Fiado(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='fiados')
    monto = models.DecimalField(**MONTO)
    descripcion = models.CharField(max_length=255, blank=True)
    fecha = models.DateField(default=timezone.localdate)
    vencimiento = models.DateField(null=True, blank=True)

    def __str__(self):
        return f'{self.cliente} · ${self.monto} · {self.fecha:%d/%m/%Y}'

    def clean(self):
        if self.vencimiento and self.fecha and self.vencimiento < self.fecha:
            raise ValidationError({'vencimiento': 'El vencimiento no puede ser anterior a la fecha del fiado.'})

    @property
    def saldo(self):
        return self.monto - (self.abonos.aggregate(t=Sum('monto'))['t'] or Decimal('0'))

    @property
    def estado(self):
        return 'Pagado' if self.saldo <= 0 else 'Pendiente'

    @property
    def vencido(self):
        return bool(self.vencimiento and self.vencimiento < timezone.localdate() and self.saldo > 0)


class Abono(models.Model):
    fiado = models.ForeignKey(Fiado, on_delete=models.CASCADE, related_name='abonos')
    monto = models.DecimalField(**MONTO)
    metodo = models.CharField(max_length=15, choices=METODOS)
    fecha = models.DateField(default=timezone.localdate)

    def __str__(self):
        return f'Abono ${self.monto} · {self.fecha:%d/%m/%Y}'


class Gasto(models.Model):
    tienda = models.ForeignKey(Tienda, on_delete=models.CASCADE)
    monto = models.DecimalField(**MONTO)
    fecha = models.DateField(default=timezone.localdate)
    categoria = models.CharField(max_length=20, choices=CATEGORIAS, default='otros')
    descripcion = models.CharField(max_length=255, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)  # trazabilidad mínima (RF-23)

    def __str__(self):
        return f'{self.get_categoria_display()} ${self.monto}'

    @property
    def editado(self):
        return (self.actualizado - self.creado).total_seconds() > 2


class Transferencia(models.Model):
    """Registro manual: no se verifica con el banco (RNF-12)."""
    tienda = models.ForeignKey(Tienda, on_delete=models.CASCADE)
    monto = models.DecimalField(**MONTO)
    fecha = models.DateField(default=timezone.localdate)
    concepto = models.CharField(max_length=150)
    tipo = models.CharField(max_length=10, choices=TIPOS_TRANSFERENCIA, default='venta')
    abono = models.OneToOneField(Abono, null=True, blank=True, on_delete=models.CASCADE, related_name='transferencia')
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.concepto} ${self.monto}'

    @property
    def editado(self):
        return (self.actualizado - self.creado).total_seconds() > 2


class CierreDiario(models.Model):
    tienda = models.ForeignKey(Tienda, on_delete=models.CASCADE, related_name='cierres')
    fecha = models.DateField()
    ventas_efectivo = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'), validators=[MinValueValidator(Decimal('0'))])
    total_transferencias_venta = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    total_gastos = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    cerrado = models.BooleanField(default=False)
    cerrado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['tienda', 'fecha'], name='un_cierre_por_dia')]

    def __str__(self):
        return f'Cierre {self.fecha:%d/%m/%Y}'

    @property
    def total_ventas(self):
        return self.ventas_efectivo + self.total_transferencias_venta
