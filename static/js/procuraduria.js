const formularioSocial = document.querySelector('[data-social-atencion]');
if (formularioSocial) {
    const agregar = formularioSocial.querySelector('[data-agregar-familiar]');
    agregar?.addEventListener('click', () => {
        const cantidad = formularioSocial.querySelector('[name="familia-TOTAL_FORMS"]');
        const indice = Number(cantidad.value);
        if (indice >= 60) return;
        const html = formularioSocial.querySelector('[data-familiar-vacio]').innerHTML.replaceAll('__prefix__', String(indice));
        formularioSocial.querySelector('[data-familia]').insertAdjacentHTML('beforeend', html);
        cantidad.value = indice + 1;
        formularioSocial.querySelector('[data-familia] fieldset:last-child input').focus();
    });
    const confirmar = formularioSocial.querySelector('[data-confirmar-finalizar]');
    formularioSocial.querySelector('[data-pedir-finalizar]').addEventListener('click', () => {
        confirmar.hidden = false;
        confirmar.querySelector('h3').focus();
    });
    formularioSocial.querySelector('[data-cancelar-finalizar]').addEventListener('click', () => {
        confirmar.hidden = true;
        formularioSocial.querySelector('[data-pedir-finalizar]').focus();
    });
}
