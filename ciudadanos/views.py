from django.db import transaction 
from django.contrib.sites.shortcuts import get_current_site
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMessage
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
import re
from django.contrib.auth.decorators import login_required, user_passes_test
import pdfplumber
import datetime
from django.utils import timezone
import random
from django.db.models import Q
from django.db.models import Case, When, Value, IntegerField


Ciudadano = get_user_model()
from .models import *

def inicio(request):
    # Obtenemos lo que el usuario escribió en el buscador (si no escribió nada, queda vacío '')
    query = request.GET.get('q', '')
    
    if query:
        # BÚSQUEDA INTELIGENTE: Busca en nombre o descripción del trámite, y en la dependencia
        lista_tramites = Tramite.objects.filter(
            Q(nombre__icontains=query) |
            Q(descripcion__icontains=query) |
            Q(direccion__nombre__icontains=query) |
            Q(direccion__descripcion__icontains=query)
        ).distinct() # distinct() evita que salgan duplicados
    else:
        # Si no buscó nada, mostramos todos
        lista_tramites = Tramite.objects.all()

    lista_direcciones = Direccion.objects.all()

    contexto = {
        'tramites': lista_tramites,
        'direcciones': lista_direcciones,
        'query': query # Le regresamos el query para que se quede escrito en la barrita
    }

    return render(request, 'ventanilla/index.html', contexto)


def registro(request):
    if request.method == 'POST':
        curp = request.POST.get('curp')
        nombre = request.POST.get('nombre')
        paterno = request.POST.get('paterno')
        materno = request.POST.get('materno')
        email = request.POST.get('email')
        password = request.POST.get('password')
        
        fecha_nacimiento = request.POST.get('fecha_nacimiento')
        cp = request.POST.get('cp')
        colonia = request.POST.get('colonia')
        calle = request.POST.get('calle')
        numero = request.POST.get('numero')
        mz_lt = request.POST.get('mz_lt')
        genero = request.POST.get('genero')
        telefono_cel = request.POST.get('telefono_cel')
        telefono_casa = request.POST.get('telefono_casa')
        
        apellidos_completos = f"{paterno} {materno}".strip()
        
        if Ciudadano.objects.filter(curp=curp).exists():
            return render(request, 'registro.html', {'error': 'Esta CURP ya está registrada.'})
            
        if Ciudadano.objects.filter(email=email).exists():
            return render(request, 'registro.html', {'error': 'Este correo electrónico ya está en uso.'})

        try:
            with transaction.atomic():
                nuevo_ciudadano = Ciudadano.objects.create_user(
                    curp=curp, email=email, password=password, 
                    nombre=nombre, apellidos=apellidos_completos
                )
                
                nuevo_ciudadano.fecha_nacimiento = fecha_nacimiento
                nuevo_ciudadano.cp = cp
                nuevo_ciudadano.colonia = colonia
                nuevo_ciudadano.calle = calle
                nuevo_ciudadano.numero = numero
                nuevo_ciudadano.mz_lt = mz_lt
                nuevo_ciudadano.genero = genero
                nuevo_ciudadano.telefono_cel = telefono_cel
                nuevo_ciudadano.telefono_casa = telefono_casa
                nuevo_ciudadano.is_active = False 
                nuevo_ciudadano.save()
                
                archivo_pdf = request.FILES.get('curp_file')
                if archivo_pdf:
                    Documento.objects.create(
                        ciudadano=nuevo_ciudadano,
                        archivo_curp=archivo_pdf,
                        verificado=False
                    )
                
                current_site = get_current_site(request)
                uid = urlsafe_base64_encode(force_bytes(nuevo_ciudadano.pk))
                token = default_token_generator.make_token(nuevo_ciudadano)
                activation_link = f"http://{current_site.domain}/activar/{uid}/{token}/"
                
                mensaje = f"Hola {nombre},\n\nGracias por registrarte en el Portal de Trámites Municipales.\n\nPara completar tu registro y activar tu cuenta, por favor haz clic en el siguiente enlace:\n\n{activation_link}"
                email_msg = EmailMessage('Activa tu cuenta ciudadana', mensaje, to=[email])
                email_msg.send()

            return render(request, 'registro_enviado.html', {'email': email})
            
        except Exception as e:
            return render(request, 'registro.html', {'error': f"Error interno: {str(e)}"})

    return render(request, 'registro.html')

def activar_cuenta(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = Ciudadano.objects.get(pk=uid)
    except(TypeError, ValueError, OverflowError, Ciudadano.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        user.is_active = True 
        user.save()
        
        documento = Documento.objects.filter(ciudadano=user).first()
        if documento:
            documento.verificado = True
            documento.save()
            
        login(request, user)
        return render(request, 'registro_exito.html')
    else:
        return render(request, 'registro_invalido.html')

def cerrar_sesion(request):
    logout(request)
    return redirect('inicio')

def iniciar_sesion(request):
    if request.method == 'POST':
        curp = request.POST.get('login_username')
        password = request.POST.get('login_password')
        
        user = authenticate(request, username=curp, password=password)
        if user is not None:
            login(request, user)
            return redirect('inicio')
        else:
            return render(request, 'index.html', {'error_login': 'CURP o contraseña incorrectos. Verifica tus datos.'})
    return redirect('inicio')

def procesar_curp_pdf(request):
    if request.method == 'POST' and request.FILES.get('curp_file'):
        pdf_file = request.FILES['curp_file']
        try:
            texto_completo = ""
            with pdfplumber.open(pdf_file) as pdf:
                for pagina in pdf.pages:
                    texto_completo += pagina.extract_text() + "\n"
            
            curp_match = re.search(r'([A-Z][AEIOU][A-Z]{2}\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[HM][A-Z]{5}[A-Z0-9]\d)', texto_completo, re.IGNORECASE)
            curp = curp_match.group(1).upper() if curp_match else ''

            lineas = [linea.strip() for linea in texto_completo.split('\n') if linea.strip()]
            nombre_completo = ""
            for i, linea in enumerate(lineas):
                if linea.upper() == "NOMBRE" and i + 1 < len(lineas):
                    nombre_completo = lineas[i+1]
                    break

            nombre_limpio = re.sub(r'[^A-ZÑÁÉÍÓÚ\s]', '', nombre_completo.upper()).strip()
            nombres, paterno, materno = "", "", ""
            if nombre_limpio:
                partes = nombre_limpio.split()
                if len(partes) >= 3:
                    materno = partes.pop()
                    paterno = partes.pop()
                    nombres = " ".join(partes)
                elif len(partes) == 2:
                    paterno = partes[0]
                    materno = partes[1]
                else:
                    nombres = nombre_limpio

            fecha_nacimiento = ""
            if curp:
                year_str = curp[4:6]
                month_str = curp[6:8]
                day_str = curp[8:10]
                year_int = int(year_str)
                year = f"19{year_str}" if year_int > 30 else f"20{year_str}"
                fecha_nacimiento = f"{day_str}/{month_str}/{year}"

            datos_extraidos = {
                'curp': curp, 'nombre': nombres, 'paterno': paterno, 
                'materno': materno, 'fecha_nacimiento': fecha_nacimiento,
            }
            return JsonResponse({'success': True, 'data': datos_extraidos})
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
            
    return JsonResponse({'success': False, 'error': 'No se recibió ningún archivo válido.'})

# --- VISTA: PERFIL CIUDADANO PROTEGIDO ---
@login_required(login_url='inicio')
def perfil_ciudadano(request):
    usuario = request.user
    documento = Documento.objects.filter(ciudadano=usuario).first()
    archivos_requisito = ArchivoRequisito.objects.filter(solicitud__ciudadano=usuario)
    
    edicion_habilitada = False
    error_password = None
    perfil_actualizado = False 
    
    if request.method == 'POST':
        if 'action_desbloquear' in request.POST:
            password_ingresada = request.POST.get('password_unlock')
            if usuario.check_password(password_ingresada):
                edicion_habilitada = True
            else:
                error_password = "La contraseña es incorrecta. Intenta de nuevo."
                
        elif 'action_guardar' in request.POST:
            nuevo_email = request.POST.get('email')
            
            if nuevo_email != usuario.email and Ciudadano.objects.filter(email=nuevo_email).exists():
                error_password = "El correo electrónico ya pertenece a otra cuenta."
                edicion_habilitada = True 
            else:
                usuario.nombre = request.POST.get('nombre', usuario.nombre)
                usuario.apellidos = request.POST.get('apellidos', usuario.apellidos)
                usuario.email = nuevo_email
                usuario.fecha_nacimiento = request.POST.get('fecha_nacimiento', usuario.fecha_nacimiento)
                usuario.telefono_cel = request.POST.get('telefono_cel', usuario.telefono_cel)
                usuario.telefono_casa = request.POST.get('telefono_casa', usuario.telefono_casa)
                
                usuario.cp = request.POST.get('cp', usuario.cp)
                usuario.colonia = request.POST.get('colonia', usuario.colonia)
                usuario.calle = request.POST.get('calle', usuario.calle) 
                usuario.numero = request.POST.get('numero', usuario.numero)
                usuario.mz_lt = request.POST.get('mz_lt', usuario.mz_lt)
                usuario.save()

                # --- SISTEMA DE DIAGNÓSTICO Y GUARDADO REAL ---
                archivos_modificados = 0
                
                for archivo in archivos_requisito:
                    input_name = f'reemplazar_doc_{archivo.id}'
                    nuevo_archivo = request.FILES.get(input_name)
                    
                    if nuevo_archivo:
                        archivo.archivo = nuevo_archivo
                        archivo.estado_validacion = 'Pendiente'
                        archivo.observaciones = ''
                        archivo.save() # Aquí se ejecuta el UPDATE real en la BDD
                        archivos_modificados += 1

                # Alertas visuales para que sepas exactamente qué pasó
                if archivos_modificados > 0:
                    messages.success(request, f"✅ ¡Se han reemplazado {archivos_modificados} documento(s) correctamente en tu expediente!")
                elif request.FILES:
                    messages.warning(request, f"⚠️ El archivo llegó, pero no coincidió. (Inputs: {list(request.FILES.keys())})")
                else:
                    messages.info(request, "Tus datos se guardaron, pero no se detectó ningún archivo PDF nuevo para reemplazar.")

                perfil_actualizado = True
                edicion_habilitada = False # Cierra el modo edición tras guardar con éxito

    return render(request, 'perfil.html', {
        'documento': documento,
        'archivos_requisito': archivos_requisito, 
        'edicion_habilitada': edicion_habilitada,
        'error_password': error_password,
        'perfil_actualizado': perfil_actualizado 
    })

#----- viwes de tramites --------------

@login_required(login_url='iniciar_sesion')
def iniciar_tramite(request, tramite_id):
    tramite = get_object_or_404(Tramite, id=tramite_id)
    # Convertimos a lista para poder inyectarle atributos temporales
    requisitos = list(tramite.requisitos.all()) 

    # 👇 1. LÓGICA DE PRE-CARGA 👇
    for req in requisitos:
        # Buscamos si ya existe un archivo aprobado para este ciudadano con la misma descripción
        archivo_previo = ArchivoRequisito.objects.filter(
            solicitud__ciudadano=request.user,
            requisito__descripcion=req.descripcion,
            estado_validacion='Aprobado' # Garantizamos que sea un doc válido
        ).order_by('-fecha_subida').first()
        
        req.archivo_previo = archivo_previo

    if request.method == 'POST':
        nueva_solicitud = Solicitud.objects.create(
            tramite=tramite,
            ciudadano=request.user
        )

        for req in requisitos:
            input_name = f'req_{req.id}'
            
            if input_name in request.FILES:
                # El usuario decidió subir un archivo nuevo
                archivo_fisico = request.FILES[input_name]
                ArchivoRequisito.objects.create(
                    solicitud=nueva_solicitud,
                    requisito=req,
                    archivo=archivo_fisico
                )
            elif req.archivo_previo:
                # 👇 2. RECICLAJE DE ARCHIVO 👇
                # El usuario no subió nada, pero tenía uno precargado. Reutilizamos el archivo.
                ArchivoRequisito.objects.create(
                    solicitud=nueva_solicitud,
                    requisito=req,
                    archivo=req.archivo_previo.archivo
                )

        messages.success(request, f'¡Tu solicitud para "{tramite.nombre}" ha sido enviada con éxito! Folio: {nueva_solicitud.folio}')
        return redirect('mis_tramites') # Te lo cambié a 'mis_tramites' para que vea su nuevo expediente

    contexto = {
        'tramite': tramite,
        'requisitos': requisitos
    }
    return render(request, 'ventanilla/detalle_tramite.html', contexto)

@login_required(login_url='iniciar_sesion')
def mis_tramites(request):
    # Definimos prioridad: Rechazado (1), Pendiente/En proceso (2), Aprobado (3)
    mis_solicitudes = Solicitud.objects.filter(ciudadano=request.user).select_related(
        'tramite__direccion'
    ).annotate(
        prioridad_estado=Case(
            When(estado='Rechazado', then=Value(1)),
            When(estado='Pendiente', then=Value(2)),
            When(estado='En proceso', then=Value(2)),
            When(estado='Aprobado', then=Value(3)),
            default=Value(4),
            output_field=IntegerField()
        )
    ).order_by('tramite__direccion__nombre', 'prioridad_estado', '-fecha_creacion')
    
    citas_usuario = Cita.objects.filter(ciudadano=request.user, estado='Programada').order_by('fecha', 'hora')
    proxima_cita = citas_usuario.first()

    for sol in mis_solicitudes:
        cita = citas_usuario.filter(tramite=sol.tramite).first()
        sol.cita_agendada = cita 

    contexto = {
        'solicitudes': mis_solicitudes,
        'proxima_cita': proxima_cita,
        'total_tramites': mis_solicitudes.count(),
    }

    return render(request, 'ventanilla/mis_tramites.html', contexto)

###############################################################################################################################

# 1. Definimos la función que comprueba si es superuser (funcionario)
def es_funcionario(user):
    return user.is_authenticated and user.is_superuser

# 2. Tu nueva vista de Login para Funcionarios
def login_funcionario(request):
    # Si ya está logueado y es superuser, lo mandamos directo al panel
    if request.user.is_authenticated and request.user.is_superuser:
        return redirect('panel_funcionario')

    if request.method == 'POST':
        curp = request.POST.get('curp')
        password = request.POST.get('password')

        # Autenticamos usando tu modelo (que usa la CURP como USERNAME_FIELD)
        user = authenticate(request, username=curp, password=password)

        if user is not None:
            # Aquí verificamos la columna is_superuser de tu tabla
            if user.is_superuser:
                login(request, user)
                return redirect('panel_funcionario')
            else:
                return render(request, 'ventanilla/login_funcionario.html', {
                    'error': 'Acceso denegado. Esta cuenta no tiene permisos de funcionario.'
                })
        else:
            return render(request, 'ventanilla/login_funcionario.html', {
                'error': 'CURP o contraseña incorrectos.'
            })

    return render(request, 'ventanilla/login_funcionario.html')


@user_passes_test(es_funcionario, login_url='login_funcionario')
def panel_funcionario(request):
    # ORDENADO POR RETRASO: Las solicitudes más antiguas (fecha de creación ascendente) aparecen primero
    todas_las_solicitudes = Solicitud.objects.all().order_by('fecha_creacion')
    
    todas_las_citas = Cita.objects.filter(estado='Programada').order_by('fecha', 'hora')
    hoy = timezone.now().date()

    citas_hoy = todas_las_citas.filter(fecha=hoy)
    citas_futuras = todas_las_citas.filter(fecha__gt=hoy)
    citas_pasadas = todas_las_citas.filter(fecha__lt=hoy)

    for sol in todas_las_solicitudes:
        cita = Cita.objects.filter(ciudadano=sol.ciudadano, tramite=sol.tramite, estado='Programada').first()
        sol.cita_agendada = cita

    contexto = {
        'solicitudes': todas_las_solicitudes,
        'citas_hoy': citas_hoy,
        'citas_futuras': citas_futuras,
        'citas_pasadas': citas_pasadas,
    }
    
    return render(request, 'ventanilla/panel_funcionario.html', contexto)

@user_passes_test(es_funcionario, login_url='login_funcionario')
def revisar_solicitud(request, solicitud_id):
    solicitud = get_object_or_404(Solicitud, id=solicitud_id)
    archivos = solicitud.archivos.all()

    if request.method == 'POST':
        nuevo_estado_gral = request.POST.get('estado_solicitud')
        if nuevo_estado_gral:
            solicitud.estado = nuevo_estado_gral
            solicitud.save()

        for archivo in archivos:
            estado_doc = request.POST.get(f'estado_doc_{archivo.id}')
            obs_doc = request.POST.get(f'obs_doc_{archivo.id}')

            if estado_doc:
                archivo.estado_validacion = estado_doc
            if obs_doc is not None:
                archivo.observaciones = obs_doc
            archivo.save()

        return redirect('panel_funcionario')

    return render(request, 'ventanilla/revisar_solicitud.html', {'solicitud': solicitud, 'archivos': archivos})

@login_required(login_url='login')
def corregir_solicitud(request, solicitud_id):
    # 👇 CAMBIO: antes filtraba por nombre_ciudadano=request.user.username
    solicitud = get_object_or_404(Solicitud, id=solicitud_id, ciudadano=request.user)
    archivos = solicitud.archivos.all()

    if request.method == 'POST':
        hubo_correcciones = False

        for archivo in archivos:
            if archivo.estado_validacion == 'Rechazado':
                input_name = f'doc_corregido_{archivo.id}'

                if input_name in request.FILES:
                    archivo.archivo = request.FILES[input_name]
                    archivo.estado_validacion = 'Pendiente'
                    archivo.observaciones = ''
                    archivo.save()
                    hubo_correcciones = True

        if hubo_correcciones:
            solicitud.estado = 'Pendiente'
            solicitud.save()

        return redirect('mis_tramites')

    return render(request, 'ventanilla/corregir_solicitud.html', {'solicitud': solicitud, 'archivos': archivos})



@login_required(login_url='iniciar_sesion')
def agendar_cita(request, solicitud_id):
    solicitud = get_object_or_404(Solicitud, id=solicitud_id, ciudadano=request.user)
    
    # Bloqueo de seguridad: Si alguien intenta entrar a la URL pero no está aprobado, lo rebotamos
    if solicitud.estado != 'Aprobado':
        messages.error(request, "Tu trámite aún no ha sido aprobado para agendar cita.")
        return redirect('mis_tramites')

    # Aquí traemos los horarios que la dependencia configuró
    horarios_disponibles = solicitud.tramite.direccion.horarios.all()

    # Si se envía el formulario del calendario por POST
    if request.method == 'POST':
        fecha_seleccionada = request.POST.get('fecha')
        hora_seleccionada = request.POST.get('hora')
        
        # Guardamos la cita en el modelo Cita que creamos en el paso anterior
        nueva_cita = Cita.objects.create(
            ciudadano=request.user,
            tramite=solicitud.tramite,
            fecha=fecha_seleccionada,
            hora=hora_seleccionada,
            estado='Programada'
        )
        messages.success(request, f"¡Tu cita ha sido agendada con éxito! Folio: {nueva_cita.folio_cita}")
        return redirect('mis_tramites')

    contexto = {
        'solicitud': solicitud,
        'horarios': horarios_disponibles
    }
    return render(request, 'ventanilla/agendar_cita.html', contexto)