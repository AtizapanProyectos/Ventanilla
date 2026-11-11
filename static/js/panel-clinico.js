const dialogoClinico = document.getElementById('clinical-dialog');
if (dialogoClinico && typeof dialogoClinico.showModal === 'function') {
    const cuerpo = dialogoClinico.querySelector('[data-dialog-body]');
    const cerrar = dialogoClinico.querySelector('[data-close-dialog]');
    let solicitud;

    async function cargar(url, opciones = {}, boton = null) {
        solicitud?.abort();
        const operacion = new AbortController();
        solicitud = operacion;
        if (boton) boton.disabled = true;
        else cuerpo.textContent = 'Cargando información clínica…';
        cuerpo.querySelector('[data-modal-error]')?.remove();
        cuerpo.setAttribute('aria-busy', 'true');
        try {
            const respuesta = await fetch(url, { ...opciones, signal: operacion.signal });
            if (!respuesta.ok || respuesta.redirected) throw new Error('Solicitud rechazada');
            cuerpo.innerHTML = await respuesta.text();
            const finalizada = cuerpo.querySelector('[data-finalizado]');
            if (opciones.method === 'POST' && finalizada) {
                const id = finalizada.dataset.finalizado;
                document.querySelectorAll(`[data-estado-cita="${id}"]`).forEach(estado => {
                    estado.textContent = 'Atendida';
                });
                document.querySelectorAll(`[data-agenda-cita="${id}"]`).forEach(cita => cita.remove());
            }
            if (!boton) cerrar.focus();
            else {
                const foco = finalizada?.querySelector('h3') ||
                    cuerpo.querySelector('.dif-field-error input, .dif-field-error textarea, [role="alert"]') ||
                    cuerpo.querySelector('h2');
                if (foco) {
                    foco.tabIndex = -1;
                    foco.focus();
                }
            }
        } catch (error) {
            if (error.name !== 'AbortError') {
                const aviso = document.createElement('p');
                aviso.className = 'dif-alert';
                aviso.dataset.modalError = '';
                aviso.setAttribute('role', 'alert');
                aviso.textContent = 'No se pudo completar la solicitud. Revisa tu acceso o inténtalo otra vez.';
                if (!boton) cuerpo.replaceChildren(aviso);
                else cuerpo.prepend(aviso);
            }
        } finally {
            if (boton) boton.disabled = false;
            if (solicitud === operacion) cuerpo.removeAttribute('aria-busy');
        }
    }

    document.addEventListener('click', evento => {
        const enlace = evento.target.closest('[data-clinical-modal]');
        if (!enlace || evento.ctrlKey || evento.metaKey || evento.shiftKey) return;
        evento.preventDefault();
        if (!dialogoClinico.open) dialogoClinico.showModal();
        cargar(enlace.href);
    });

    cuerpo.addEventListener('submit', evento => {
        const formulario = evento.target.closest('[data-clinical-form]');
        if (!formulario) return;
        evento.preventDefault();
        if (formulario.hasAttribute('data-finalizar-consulta')) {
            const confirmacion = formulario.querySelector('[data-confirmacion]');
            confirmacion.hidden = false;
            confirmacion.querySelector('h3').focus();
            return;
        }
        cargar(formulario.action, { method: 'POST', body: new FormData(formulario) }, evento.submitter);
    });

    cuerpo.addEventListener('click', evento => {
        const boton = evento.target.closest('[data-seguir-editando], [data-confirmar-cierre]');
        if (!boton) return;
        const formulario = boton.form;
        if (boton.hasAttribute('data-seguir-editando')) {
            formulario.querySelector('[data-confirmacion]').hidden = true;
            formulario.querySelector('button[type="submit"]').focus();
        } else if (formulario.reportValidity()) {
            cargar(formulario.action, { method: 'POST', body: new FormData(formulario) }, boton);
        }
    });

    cuerpo.addEventListener('keydown', evento => {
        const campo = evento.target;
        if (evento.key !== 'Enter' || evento.shiftKey || evento.isComposing ||
            !campo.matches('input:not([type="hidden"]), textarea, select')) return;
        const formulario = campo.closest('[data-finalizar-consulta]');
        if (!formulario) return;
        evento.preventDefault();
        if (!campo.reportValidity()) return;
        const campos = Array.from(formulario.querySelectorAll(
            'input:not([type="hidden"]):enabled, textarea:enabled, select:enabled'
        ));
        const siguiente = campos[campos.indexOf(campo) + 1];
        const seccion = siguiente?.closest('details');
        if (seccion) seccion.open = true;
        (siguiente || formulario.querySelector('button[type="submit"]')).focus();
    });

    cerrar.addEventListener('click', () => dialogoClinico.close());
    dialogoClinico.addEventListener('close', () => {
        solicitud?.abort();
        cuerpo.replaceChildren();
    });
}
