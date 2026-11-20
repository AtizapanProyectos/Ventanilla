# Procuraduría Social

La migración 0014 crea Estudio Socioeconómico y Consulta Psicológica. No crea sedes ni horarios ficticios.

La migración 0017 habilita psicología con el horario autorizado: lunes a viernes de 09:00 a 16:00, citas de 45 minutos y cupo de una persona. Utiliza la sede Sistema Municipal DIF con municipio y estado; la dirección de calle puede completarse en Admin. No reemplaza horarios configurados previamente. En psicología se precargan Atizapán de Zaragoza y Estado de México cuando faltan esos datos y se pasa directamente a la agenda, sin revisión documental.

## Configuración en Django Admin

1. En **Sede socials**, registrar nombre y dirección reales y marcar activa.
2. En **Horario socials**, seleccionar trámite, sede, día, inicio, fin, duración en minutos y cupo por turno. Repetir para los días y trámites atendidos. Se rechazan horarios superpuestos del mismo servicio y sede.
3. En **Trámites**, revisar costo y tiempo de respuesta de ambos servicios. El importe del estudio se registra al atender; no se cobra en línea.
4. Crear grupos con los permisos correspondientes sobre solicitudes: **revisar procuraduria**, **atender socioeconomico**, **atender psicologia**. Cada cuenta de personal debe estar activa y tener acceso de staff. Asignar únicamente los permisos de su función.
5. Completar nombre, apellidos y cédula profesional de las cuentas del personal. Se incorporan al documento final.

## Operación

El ciudadano elige al titular o a un beneficiario de su cuenta. Se recuperan datos conocidos y se solicitan los faltantes. Los documentos y datos de personas distintas permanecen separados. El RFC empresarial no se utiliza como RFC personal.

El estudio solicita comprobantes de domicilio e ingresos de hasta tres meses e identificación del peticionario. La modalidad general agrega la solicitud institucional; beca agrega también boleta o comprobante de estudios; judicial utiliza oficio judicial en lugar de solicitud institucional.

Los archivos son PDF de hasta 5 MB. Como en Alta de Proveedor, el personal abre cada documento, elige Pendiente, Documento Válido o Rechazado y puede agregar observaciones. La vigencia se comprueba visualmente en el documento; no se capturan fechas ni casillas de vencimiento. Los documentos aprobados del mismo contexto se vinculan automáticamente. Los archivos históricos de otros módulos pasan a revisión del personal sin duplicarse. La agenda se habilita cuando todos los documentos obligatorios están aprobados.

Psicología no exige archivos, conforme a los requisitos recibidos. Después de completar datos permite agendar directamente. Una nueva sesión se inicia como una nueva solicitud, conservando los datos del beneficiario.

La agenda publica cuatro semanas y verifica disponibilidad al confirmar. Sin horarios configurados muestra que todavía no hay turnos publicados. El comprobante incluye fecha, hora, sede, persona y cuenta responsable.

El personal opera desde el panel de funcionarios: valida documentos, atiende citas y guarda borradores. Para finalizar un estudio debe registrar diagnóstico, conclusión, pago, importe, fecha, recibo y libro de gobierno. La atención puede registrarse a partir de la fecha de la cita.

Al finalizar se conserva un Word y un PDF en la misma atención. El estudio utiliza la plantilla oficial de `Tramites/Estudio Socioeconomico Procuraduria.docx`; psicología utiliza una ficha de atención con motivo, valoración, atención, recomendaciones y seguimiento. El personal autorizado y la cuenta responsable pueden abrir, descargar e imprimir los formatos. Las atenciones finalizadas son de solo lectura.

## Despliegue

Se requiere `python-docx` y LibreOffice Writer. Nixpacks instala Writer y las fuentes; el arranque ejecuta las migraciones. Para desarrollo local, instalar LibreOffice o definir `LIBREOFFICE_BIN` con su ejecutable. Si la conversión falla, el borrador se conserva y la cita no se marca como atendida; se puede reintentar.
