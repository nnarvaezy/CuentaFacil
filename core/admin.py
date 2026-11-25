from django.contrib import admin
from .models import Tienda, Cliente, Fiado, Abono, Gasto, Transferencia, CierreDiario
for modelo in (Tienda, Cliente, Fiado, Abono, Gasto, Transferencia, CierreDiario):
    admin.site.register(modelo)
