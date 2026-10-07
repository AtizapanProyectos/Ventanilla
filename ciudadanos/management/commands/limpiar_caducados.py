from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from ciudadanos.models import Documento

class Command(BaseCommand):
    help = 'Borra documentos físicos no verificados de más de 48 horas, conservando el registro del ciudadano'

    def handle(self, *args, **kwargs):
        # 1. Calculamos la fecha y hora de hace exactamente 48 horas
        limite_tiempo = timezone.now() - timedelta(hours=48)
        
        # 2. Buscamos documentos que NO estén verificados y sean más viejos que el límite
        documentos_viejos = Documento.objects.filter(verificado=False, fecha_subida__lt=limite_tiempo)
        
        contador = 0
        for doc in documentos_viejos:
            
            # A) Borramos físicamente el archivo PDF del disco duro para no saturar el servidor
            if doc.archivo_curp:
                doc.archivo_curp.delete(save=False) 
            
            # B) Borramos la fila del documento pendiente en la base de datos
            doc.delete()
            
            # ¡ELIMINAMOS LA REGLA DE BORRAR AL CIUDADANO!
            # El usuario.is_active = False se queda en la base de datos permanentemente para tu revisión.
                
            contador += 1
            
        # Mensaje de éxito que se imprimirá en la terminal
        self.stdout.write(self.style.SUCCESS(f'Limpieza completada: Se eliminaron {contador} PDFs caducados. Las cuentas de ciudadano siguen intactas.'))