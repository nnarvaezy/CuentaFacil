from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Cliente, Fiado, Abono, Gasto, Transferencia, METODOS


def monto():
    return forms.NumberInput(attrs={'placeholder': '0.00', 'step': '0.01', 'inputmode': 'decimal'})


def fecha():
    return forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class Placeholders:
    def poner_placeholders(self):
        for campo in self.fields.values():
            campo.widget.attrs.setdefault('placeholder', campo.label or '')


class RegistroForm(Placeholders, UserCreationForm):
    field_order = ['first_name', 'nombre_tienda', 'email', 'password1', 'password2', 'telefono', 'cedula', 'direccion']
    first_name = forms.CharField(max_length=120, label='Nombre completo')
    nombre_tienda = forms.CharField(max_length=120, label='Nombre de la tienda')
    email = forms.EmailField(label='Correo electrónico')
    telefono = forms.CharField(max_length=20, required=False, label='Teléfono (opcional)')
    cedula = forms.CharField(max_length=10, required=False, label='Cédula (opcional)')
    direccion = forms.CharField(max_length=200, required=False, label='Dirección (opcional)')

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ['first_name', 'email']

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields['password1'].label, self.fields['password2'].label = 'Contraseña', 'Confirmar contraseña'
        self.poner_placeholders()

    def clean_email(self):
        correo = self.cleaned_data['email'].lower()
        if User.objects.filter(email__iexact=correo).exists() or User.objects.filter(username__iexact=correo).exists():
            raise forms.ValidationError('Este correo ya está registrado.')
        return correo

    def clean_cedula(self):
        c = self.cleaned_data['cedula'].strip()
        if c and not (c.isdigit() and len(c) == 10):
            raise forms.ValidationError('La cédula debe tener 10 dígitos.')
        return c

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data['email']  # el correo es el usuario de acceso
        if commit:
            user.save()
        return user


class LoginForm(Placeholders, AuthenticationForm):
    recordarme = forms.BooleanField(
        required=False,
        initial=True,
        label='Recordarme'
    )

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields['username'].label = 'Correo electrónico'
        self.fields['password'].label = 'Contraseña'
        self.poner_placeholders()
        self.fields['username'].widget.attrs.update({'autofocus': True, 'inputmode': 'email'})

    def clean_username(self):
        return self.cleaned_data['username'].strip().lower()


class PinForm(forms.Form):
    pin = forms.RegexField(regex=r'^\d{5}$', label='PIN de 5 dígitos', error_messages={'invalid': 'El PIN son 5 números.'},
                           widget=forms.PasswordInput(attrs={'inputmode': 'numeric', 'maxlength': 5, 'autocomplete': 'off', 'autofocus': True}))


class PinConfigForm(PinForm):
    pin2 = forms.CharField(label='Repite el PIN', widget=forms.PasswordInput(attrs={'inputmode': 'numeric', 'maxlength': 5}))

    def clean(self):
        d = super().clean()
        if d.get('pin') and d.get('pin') != d.get('pin2'):
            self.add_error('pin2', 'Los PIN no coinciden.')
        return d


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ['nombre', 'telefono', 'referencia']


class FiadoForm(forms.ModelForm):
    class Meta:
        model = Fiado
        fields = ['cliente', 'monto', 'fecha', 'vencimiento', 'descripcion']
        widgets = {'monto': monto(), 'fecha': fecha(), 'vencimiento': fecha()}
        labels = {'monto': 'Monto del fiado', 'vencimiento': 'Vencimiento (opcional)', 'descripcion': 'Descripción (opcional)'}


class AbonoForm(forms.ModelForm):
    class Meta:
        model = Abono
        fields = ['fiado', 'monto', 'metodo', 'fecha']
        widgets = {'monto': monto(), 'fecha': fecha()}
        labels = {'monto': 'Monto del abono', 'metodo': 'Método de pago'}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields['metodo'].choices = METODOS  # sin opción en blanco
        self.fields['metodo'].initial = 'efectivo'


class SinFuturo:
    def clean_fecha(self):
        fecha = self.cleaned_data['fecha']
        if fecha > timezone.localdate():
            raise ValidationError('La fecha no puede ser futura.')
        return fecha


class GastoForm(SinFuturo, forms.ModelForm):
    class Meta:
        model = Gasto
        fields = ['monto', 'fecha', 'categoria', 'descripcion']
        widgets = {'monto': monto(), 'fecha': fecha()}
        labels = {'categoria': 'Categoría', 'descripcion': 'Descripción (opcional)'}


class TransferenciaForm(SinFuturo, forms.ModelForm):
    fiado = forms.ModelChoiceField(queryset=Fiado.objects.none(), required=False, label='Fiado que se abona', empty_label='— Selecciona —')
    field_order = ['tipo', 'fiado', 'monto', 'fecha', 'concepto']

    class Meta:
        model = Transferencia
        fields = ['tipo', 'monto', 'fecha', 'concepto']
        widgets = {'monto': monto(), 'fecha': fecha()}
        labels = {'tipo': 'Tipo de transferencia'}

    def clean(self):
        d = super().clean()
        if d.get('tipo') == 'abono':
            if not d.get('fiado'):
                self.add_error('fiado', 'Selecciona el fiado que se está abonando.')
            elif d.get('monto') and d['monto'] > d['fiado'].saldo:
                self.add_error('monto', f"El abono supera la deuda pendiente (${d['fiado'].saldo}).")
        return d


class TransferenciaEditForm(SinFuturo, forms.ModelForm):
    class Meta:
        model = Transferencia
        fields = ['monto', 'fecha', 'concepto']
        widgets = {'monto': monto(), 'fecha': fecha()}


class EfectivoForm(forms.Form):
    ventas_efectivo = forms.DecimalField(min_value=0, max_digits=12, decimal_places=2, label='Ventas en efectivo del día')
