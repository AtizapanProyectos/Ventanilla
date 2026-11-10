document.addEventListener('DOMContentLoaded', function() {
    
    // --- 1. LÓGICA DE CARGA DE ARCHIVO (AUTOMÁTICA Y DRAG & DROP) ---
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('curp-file');

    function procesarArchivo(file) {
        if (!file || file.type !== "application/pdf") {
            alert("Seguridad: Por favor, sube únicamente el documento PDF oficial.");
            resetDropZone();
            return;
        }

        dropZone.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="var(--teal)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="spin"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
            <span style="color: var(--teal);">Extrayendo datos de forma segura...</span>
        `;
        dropZone.style.borderColor = "var(--teal)";
        dropZone.style.background = "var(--teal-bg)";
        dropZone.style.pointerEvents = "none"; 

        const formData = new FormData();
        formData.append('curp_file', file);
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

        fetch('/api/procesar-curp/', {
            method: 'POST',
            body: formData,
            headers: { 'X-CSRFToken': csrfToken }
        })
        .then(response => response.json())
        .then(result => {
            if(result.success) {
                // Autocompletar campos visuales
                document.getElementById('ext-curp').value = result.data.curp;
                document.getElementById('ext-nombre').value = result.data.nombre;
                document.getElementById('ext-paterno').value = result.data.paterno;
                document.getElementById('ext-materno').value = result.data.materno;
                document.getElementById('ext-fecha').value = result.data.fecha_nacimiento;
                
                dropZone.innerHTML = `
                    <svg viewBox="0 0 24 24" fill="none" stroke="var(--teal)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                    <span style="color: var(--teal);">¡Datos autocompletados correctamente!</span>
                `;
            } else {
                alert("Error al leer el documento: " + result.error);
                resetDropZone();
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert("Error de conexión con el servidor.");
            resetDropZone();
        });
    }

    function resetDropZone() {
        dropZone.style.pointerEvents = "auto";
        dropZone.style.borderColor = "var(--p400)";
        dropZone.style.background = "var(--p50)";
        dropZone.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="var(--p600)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
            <span>Haz clic o arrastra aquí tu archivo de CURP</span>
            <small>Solo se admiten documentos en formato PDF oficial</small>
        `;
        fileInput.value = "";
    }

    if(dropZone && fileInput) {
        dropZone.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', function() {
            if(this.files && this.files[0]) procesarArchivo(this.files[0]);
        });

        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault(); 
            dropZone.style.borderColor = "var(--p600)";
            dropZone.style.background = "var(--p100)";
        });

        dropZone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            dropZone.style.borderColor = "var(--p400)";
            dropZone.style.background = "var(--p50)";
        });

        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.style.borderColor = "var(--p400)";
            dropZone.style.background = "var(--p50)";
            if(e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                fileInput.files = e.dataTransfer.files; 
                procesarArchivo(e.dataTransfer.files[0]); 
            }
        });
    }


    // --- 3. LÓGICA DEL SELECT PERSONALIZADO (GÉNERO) ---
    const generoBox = document.getElementById('genero-box');
    const generoDropdown = document.getElementById('genero-dropdown');
    const generoInput = document.getElementById('genero-input');
    const generoText = document.getElementById('genero-text');

    if (generoBox && generoDropdown) {
        // Abrir/cerrar menú
        generoBox.addEventListener('click', function(e) {
            e.stopPropagation();
            generoDropdown.classList.toggle('show');
            generoBox.style.borderColor = "var(--teal)"; // Resalte al abrir
        });

        // Seleccionar opción
        const opciones = generoDropdown.querySelectorAll('.dropdown-item');
        opciones.forEach(opcion => {
            opcion.addEventListener('click', function() {
                const valor = this.getAttribute('data-value');
                generoInput.value = valor;       // Guardar el valor en el input oculto
                generoText.textContent = valor;  // Mostrarlo al ciudadano
                generoBox.classList.add('has-value');
                generoDropdown.classList.remove('show');
                generoBox.style.borderColor = "var(--p200)"; // Restaurar borde normal
                generoBox.classList.remove('input-error'); // Limpiar alertas de error
            });
        });

        // Cerrar al hacer clic afuera
        document.addEventListener('click', function(e) {
            if (!generoBox.contains(e.target) && !generoDropdown.contains(e.target)) {
                generoDropdown.classList.remove('show');
                if(!generoInput.value) generoBox.style.borderColor = "var(--p200)";
            }
        });
    }

   // --- 4. VALIDACIONES ESTRICTAS DE SEGURIDAD ---
    const formRegistro = document.getElementById("form-registro");
    const pwdInput = document.getElementById("password");
    const pwdConfInput = document.getElementById("password-conf");
    const errorMsg = document.getElementById("password-error");

    if(pwdInput && pwdConfInput) {
        const limpiarError = () => {
            pwdInput.classList.remove('input-error');
            pwdConfInput.classList.remove('input-error');
            if(errorMsg) errorMsg.style.display = 'none';
        };
        pwdInput.addEventListener('input', limpiarError);
        pwdConfInput.addEventListener('input', limpiarError);
    }
    
    if (formRegistro) {
        formRegistro.addEventListener("submit", function(e) {
            
            // A. Verificar que el OCR se completó
            const extNombre = document.getElementById("ext-nombre").value;
            if(!extNombre) {
                e.preventDefault();
                alert("Por favor carga tu documento de CURP y extrae los datos antes de continuar.");
                return;
            }

            // B. Verificar que el Género esté seleccionado
            const generoVal = document.getElementById("genero-input");
            if(generoVal && !generoVal.value) {
                e.preventDefault();
                if(generoBox) generoBox.classList.add('input-error');
                alert("Por favor selecciona tu género.");
                return;
            }

           // --- VALIDACIÓN VISUAL DE TELÉFONOS ---
            const telCelInput = document.getElementById("telefono-cel");
            const telCasaInput = document.getElementById("telefono-casa");
            const telErrorMsg = document.getElementById("telefono-error");
            
            const telCel = telCelInput ? telCelInput.value.trim() : "";
            const telCasa = telCasaInput ? telCasaInput.value.trim() : "";
            const regexTel = /^\d{10}$/;

            // Limpiar errores visuales previos
            if(telCelInput) telCelInput.closest('div').style.borderColor = "var(--p200)";
            if(telCasaInput) telCasaInput.closest('div').style.borderColor = "var(--p200)";
            if(telCelInput) telCelInput.classList.remove('input-error');
            if(telCasaInput) telCasaInput.classList.remove('input-error');
            if(telErrorMsg) telErrorMsg.style.display = 'none';

            // Función para limpiar al escribir
            const limpiarTelError = () => {
                if(telCelInput) {
                    telCelInput.classList.remove('input-error');
                    telCelInput.closest('div').style.borderColor = "var(--p200)";
                }
                if(telCasaInput) {
                    telCasaInput.classList.remove('input-error');
                    telCasaInput.closest('div').style.borderColor = "var(--p200)";
                }
                if(telErrorMsg) telErrorMsg.style.display = 'none';
            };

            if(telCelInput) telCelInput.addEventListener('input', limpiarTelError);
            if(telCasaInput) telCasaInput.addEventListener('input', limpiarTelError);

            if (!telCel && !telCasa) {
                e.preventDefault();
                e.stopPropagation();
                if(telCelInput) {
                    telCelInput.classList.add('input-error');
                    telCelInput.closest('div').style.borderColor = "#ef4444";
                }
                if(telCasaInput) {
                    telCasaInput.classList.add('input-error');
                    telCasaInput.closest('div').style.borderColor = "#ef4444";
                }
                if(telErrorMsg) {
                    telErrorMsg.textContent = "Atención: Es obligatorio registrar al menos un número telefónico (Celular o Casa) de 10 dígitos.";
                    telErrorMsg.style.display = "block";
                }
                if(telCelInput) telCelInput.focus();
                return false;
            }

            if (telCel && !regexTel.test(telCel)) {
                e.preventDefault();
                e.stopPropagation();
                if(telCelInput) {
                    telCelInput.classList.add('input-error');
                    telCelInput.closest('div').style.borderColor = "#ef4444";
                }
                if(telErrorMsg) {
                    telErrorMsg.textContent = "El Teléfono Celular debe contener exactamente 10 dígitos numéricos.";
                    telErrorMsg.style.display = "block";
                }
                if(telCelInput) telCelInput.focus();
                return false;
            }

            if (telCasa && !regexTel.test(telCasa)) {
                e.preventDefault();
                e.stopPropagation();
                if(telCasaInput) {
                    telCasaInput.classList.add('input-error');
                    telCasaInput.closest('div').style.borderColor = "#ef4444";
                }
                if(telErrorMsg) {
                    telErrorMsg.textContent = "El Teléfono de Casa debe contener exactamente 10 dígitos numéricos.";
                    telErrorMsg.style.display = "block";
                }
                if(telCasaInput) telCasaInput.focus();
                return false;
            }

            if (telCasa && !regexTel.test(telCasa)) {
                e.preventDefault();
                e.stopPropagation();
                if(telCasaInput) telCasaInput.classList.add('input-error');
                alert("El Teléfono de Casa debe contener exactamente 10 dígitos numéricos.");
                telCasaInput.focus();
                return false;
            }

            // D. Política de Contraseña (Mín. 6, 1 Número, 1 Signo)
            const pwd = pwdInput.value;
            const pwdConf = pwdConfInput.value;
            const regexPassword = /^(?=.*\d)(?=.*[^a-zA-Z0-9\s]).{6,}$/;
            
            if (!regexPassword.test(pwd)) {
                e.preventDefault(); 
                pwdInput.classList.add('input-error');
                if(errorMsg) {
                    errorMsg.textContent = "Contraseña rechazada: Debe tener al menos 6 caracteres, incluir 1 número y 1 signo.";
                    errorMsg.style.display = "block";
                }
                return;
            }

            if(pwd !== pwdConf) {
                e.preventDefault();
                pwdConfInput.classList.add('input-error');
                if(errorMsg) {
                    errorMsg.textContent = "Validación rechazada: Las contraseñas no coinciden.";
                    errorMsg.style.display = "block";
                }
                return;
            }

            // E. Verificación Oficial de Google reCAPTCHA
            const recaptchaResponse = grecaptcha.getResponse();
            if(recaptchaResponse.length === 0) {
                e.preventDefault();
                alert("Seguridad: Por favor, marca la casilla 'No soy un robot'.");
                return;
            }

        });
    }
});