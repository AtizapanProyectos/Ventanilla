document.querySelectorAll('form').forEach(formulario => {
    const tipo = formulario.querySelector('[name="tipo_persona"]');
    if (!tipo) return;
    const razon = formulario.querySelector('[name="razon_social"]');
    const representante = formulario.querySelector('[name="tiene_representante"]');
    const rfc = formulario.querySelector('[name="rfc"]');
    const esRegistro = formulario.id === 'form-registro';
    function actualizar() {
        const moral = tipo.value === 'moral';
        razon.required = moral;
        razon.closest('.input-group, .dif-field').hidden = !moral;
        representante.closest('.dif-field, label').hidden = moral;
        if (moral) representante.checked = true;
        if (esRegistro) rfc.required = moral;
    }
    tipo.addEventListener('change', actualizar);
    actualizar();
});
