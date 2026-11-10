document.querySelectorAll('[data-wizard]').forEach(form => {
    const fases = Array.from(form.querySelectorAll('[data-phase]'));
    const pasos = Array.from(form.querySelectorAll('[data-step]'));
    const anterior = form.querySelector('[data-prev]');
    const siguiente = form.querySelector('[data-next]');
    const enviar = form.querySelector('[data-submit]');
    let actual = Math.max(0, fases.findIndex(fase => fase.querySelector('.dif-field-error')));

    function mostrar(indice, enfocar = false) {
        actual = indice;
        fases.forEach((fase, i) => { fase.hidden = i !== actual; });
        pasos.forEach((paso, i) => {
            if (i === actual) paso.setAttribute('aria-current', 'step');
            else paso.removeAttribute('aria-current');
        });
        anterior.hidden = actual === 0;
        siguiente.hidden = actual === fases.length - 1;
        enviar.hidden = !siguiente.hidden;
        if (enfocar) fases[actual].querySelector('legend').focus();
    }

    siguiente.addEventListener('click', () => {
        const invalido = fases[actual].querySelector(':invalid');
        if (invalido) invalido.reportValidity();
        else mostrar(actual + 1, true);
    });
    anterior.addEventListener('click', () => mostrar(actual - 1, true));
    form.addEventListener('invalid', evento => {
        const indice = fases.indexOf(evento.target.closest('[data-phase]'));
        const primero = form.querySelector('input:invalid, textarea:invalid, select:invalid');
        if (indice !== -1 && evento.target === primero) mostrar(indice);
    }, true);
    mostrar(actual);
});

document.querySelectorAll('[data-agenda]').forEach(form => {
    const calendario = form.querySelector('[data-calendar]');
    const dias = Array.from(calendario.querySelectorAll('[data-day]:enabled'));
    const grupos = Array.from(form.querySelectorAll('[data-slots]'));
    const resumen = form.querySelector('[data-selection]');
    const confirmar = form.querySelector('[data-submit]');
    const inicial = resumen.textContent;
    calendario.hidden = false;
    form.querySelector('[data-empty]').hidden = dias.length !== 0;

    function actualizar() {
        const turno = form.querySelector('input[name="turno"]:checked');
        resumen.textContent = turno ? turno.dataset.summary : inicial;
        confirmar.disabled = !turno;
    }

    function mostrar(dia) {
        dias.forEach(boton => boton.setAttribute('aria-pressed', String(boton === dia)));
        grupos.forEach(grupo => {
            grupo.hidden = grupo.dataset.slots !== dia.dataset.day;
            const elegido = grupo.querySelector(':checked');
            if (grupo.hidden && elegido) elegido.checked = false;
        });
        actualizar();
    }

    dias.forEach(dia => dia.addEventListener('click', () => mostrar(dia)));
    form.addEventListener('change', actualizar);
    if (dias.length) mostrar(dias.find(dia => grupos.some(
        grupo => grupo.dataset.slots === dia.dataset.day && grupo.querySelector('input:enabled')
    )) || dias[0]);
    actualizar();
});

document.querySelectorAll('[data-busy-form]').forEach(form => {
    form.addEventListener('submit', () => {
        const boton = form.querySelector('[data-submit]');
        boton.disabled = true;
        boton.textContent = 'Guardando…';
        form.setAttribute('aria-busy', 'true');
    });
    window.addEventListener('pageshow', evento => {
        if (!evento.persisted) return;
        form.removeAttribute('aria-busy');
        window.location.reload();
    });
});
