// ==========================================================================
// 1. LÓGICA DEL BUSCADOR GENERAL
// ==========================================================================
function fill(t) {
    const q = document.getElementById('q');
    if (q) q.value = t;
}

function buscar() {
    const qElem = document.getElementById('q');
    if (!qElem) return;
    
    var q = qElem.value.trim();
    if (q) {
        alert('Buscando: "' + q + '"\n\n↳ Conecta con tu vista de Django:\nreturn redirect("/tramites/?q=" + q)');
    }
}

const searchInput = document.getElementById('q');
if (searchInput) {
    searchInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') buscar();
    });
}

// ==========================================================================
// 2. LÓGICA DEL MENÚ DE INICIO DE SESIÓN (MODO DESCONECTADO)
// ==========================================================================
const btnLoginToggle = document.getElementById('btn-login-toggle');
const loginDropdown = document.getElementById('login-dropdown');
const loginForm = document.getElementById('login-form');

if (btnLoginToggle && loginDropdown) {
    btnLoginToggle.addEventListener('click', function(e) {
        e.stopPropagation(); 
        loginDropdown.classList.toggle('show');
    });

    document.addEventListener('click', function(e) {
        if (!loginDropdown.contains(e.target) && !btnLoginToggle.contains(e.target)) {
            loginDropdown.classList.remove('show');
        }
    });
    
    loginDropdown.addEventListener('click', function(e) {
        e.stopPropagation();
    });
}

if (loginForm) {
    loginForm.addEventListener('submit', function(e) {
        // Listo para enviar a Django
    });
}

// ==========================================================================
// 3. LÓGICA DEL MENÚ DESPLEGABLE DEL PERFIL (MODO CONECTADO)
// ==========================================================================
document.addEventListener('DOMContentLoaded', function() {
    const btnPerfil = document.getElementById('btn-mi-perfil');
    const menuPerfil = document.getElementById('menu-mi-perfil');

    if (btnPerfil && menuPerfil) {
        btnPerfil.addEventListener('click', function(e) {
            e.stopPropagation(); 
            menuPerfil.classList.toggle('show');
            if(menuPerfil.classList.contains('show')) {
                btnPerfil.style.borderColor = "var(--teal)";
            } else {
                btnPerfil.style.borderColor = "var(--p400)";
            }
        });

        document.addEventListener('click', function(e) {
            if (!menuPerfil.contains(e.target) && !btnPerfil.contains(e.target)) {
                menuPerfil.classList.remove('show');
                btnPerfil.style.borderColor = "var(--p400)";
            }
        });
    }
});

// ==========================================================================
// 4. LÓGICA DEL FORMULARIO DE PERFIL CIUDADANO
// ==========================================================================
document.addEventListener('DOMContentLoaded', function() {
    const cpInput = document.getElementById('cp-input');
    const coloniaInput = document.getElementById('colonia-input');
    const coloniaDropdown = document.getElementById('colonia-dropdown');

    // Catálogo Estricto de Atizapán
    const coloniasData = {
        "52900": ["Atizapan 1", "Atizapan Centro", "Bosques de Atizapan", "Colonial Atizapan", "Comonfort", "Cond Chabacanos", "Coporo 11 B", "Coporo 31-rincon del Bosque", "El Roble", "Fovissste", "Imperial de Bellavista", "La Hermita", "La Palma", "Las Acacias", "Mediterraneo", "Oasis", "Porfirio Diaz", "Residencial Batel", "Residencial del Bosque", "Residencial la Palma 4", "Residencial Real de San Francisco", "Residencial San Mateo"],
        "52909": ["Las Flores"],
        "52910": ["1ro de Septiembre", "6 de Octubre", "Adolfo Lopez Mateos", "Adolfo Lopez Mateos - los Olivos", "Adolfo Lopez Mateos Seccion Maria Luisa", "Arbolada del Pedregal", "Hacienda del Pedregal Secc Herradura", "Hogares de Atizapan", "Real del Pedregal", "Sagitario 1"],
        "52915": ["Alamos", "Atizapan 2000", "El Capulin", "El Capulin 2da Seccion", "Jose Ma Morelos y Pavon", "Lomas de las Torres", "Mexico 86", "Villa de las Torres"],
        "52916": ["Ex - Hacienda del Pedregal - Lopez Mateos 2da Seccion", "Ex - Hacienda del Pedregal - Tierra de Enmedio"],
        "52917": ["La Nueva Era"],
        "52918": ["Emiliano Zapata", "General Cardenas del Rio", "Hacienda del Pedregal", "Lomas de Monte Maria", "Miraflores", "Villa de las Palmas", "Villa de las Palmas- Mirador las Torres"],
        "52919": ["Bosques de Ixtacala", "Bosques de Primavera", "Revolucion", "Uam"],
        "52920": ["Cerro Grande", "El Cerrito", "Las Peñitas", "San Antonio los Pocitos", "San Mateo Tecoloapan"],
        "52923": ["Casa Blanca I", "Villa Jardin"],
        "52924": ["San Jose del Jaral 1ra Seccion", "San Jose el Jaral", "San Jose el Jaral 2da Seccion"],
        "52925": ["Club de Golf Hacienda", "LOmas de la Hacienda"],
        "52926": ["Jardines de Monterrey", "Margarita Maza de Juarez", "Villas San Jose"],
        "52927": ["San Miguel Xochimanga"],
        "52928": ["Ejido San Miguel Chalma", "El Campanario", "Lomas de San Miguel", "Lomas de Tepalcapa", "Prados de Ixtacala", "Prados de Ixtacala 2da Seccion", "San Juan Ixtacala Plano Norte", "San Juan Ixtacala Plano Sur"],
        "52929": ["Hacienda de la Luz", "Villas de la Hacienda", "Villas Fortuna"],
        "52930": ["Chiluca y Club de Golf Chiluca", "La Estadia", "Lago Esmeralda", "Lomas de Valle Escondido", "Real Esmeralda", "Vista Esmeralda"],
        "52937": ["Hacienda de Valle Escondido", "Plaza Praga", "Residencial Prado Largo"],
        "52938": ["Condado de Sayavedra", "Fincas de Sayavedra"],
        "52940": ["5 de Mayo", "Alfredo V Bonfil", "Luis Donaldo Colosio - Rinconada Bonfil", "Profesor Cristobal Higuera"],
        "52945": ["Las Arboledas", "Real de Atizapan", "Vergel de Arboledas"],
        "52946": ["La Planada - la Explanada", "San Juan Bosco 1"],
        "52947": ["Casas Lindas", "La Cima", "Lomas Lindas"],
        "52948": ["Balcones de Bellavista", "Pedregal de Atizapan", "Riachuelo Lomas del Pedregal", "Sin Nombre"],
        "52949": ["Las Aguilas", "Marcella Ii"],
        "52950": ["Las Arboledas"],
        "52953": ["Ahuehuetes", "Colinas de Laureles", "Las Colonias", "Torres de Atizapan 6", "Torres de Atizapan 8"],
        "52957": ["Mayorazgos de los Gigantes", "Mayorazgos del Bosque"],
        "52959": ["Club de Golf Hacienda"],
        "52960": ["Barrio Norte", "Colinas de Atizapan", "Residencial las Flores"],
        "52965": ["La Condesa"],
        "52966": ["Mexico Nuevo", "Residencial los Angeles"],
        "52970": ["Las Alamedas", "Ruiz Cortinez", "San Jose Ii", "Valle de Mexico"],
        "52975": ["El Mosco", "El Potrero", "Lomas de San Lorenzo", "Rincon de la Montaña"],
        "52976": ["Atizapan Moderno"],
        "52977": ["Lomas de Atizapan"],
        "52978": ["Jardines de Atizapan", "Residencial Casa Blanca Ii"],
        "52979": ["Alborada", "Lazaro Cardenas"],
        "52980": ["Bosques de San Martin", "San Martin", "San Martin de Porres"],
        "52985": ["Cerro Madrid", "La Cruz", "Morelos"],
        "52986": ["Ignacio Lopez Rayon"],
        "52987": ["Demetrio Vallejo", "La Cañada", "Ruiseñor"],
        "52988": ["Capistrano"],
        "52989": ["Madin", "Nuevo Madin"],
        "52990": ["De las Golondrinas", "El Chaparral", "Lomas de Guadalupe", "Residencial Calacoaya"],
        "52994": ["Lomas de Bellavista"],
        "52995": ["Club de Golf Bellavista"],
        "52996": ["Calacoaya", "Rincon Colonial"],
        "52997": ["El Calvario", "Mayorazgos de la Concordia"],
        "52998": ["Fuentes de Satelite", "Rancho Castro"],
        "53126": ["6ta Seccion Lomas Verdes"],
        "54945": ["Paseo Real"],
        "54970": ["El Capulin"],
        "54978": ["Las Acacias"]
    };

    if (cpInput && coloniaInput && coloniaDropdown && !cpInput.readOnly) {
        
        cpInput.addEventListener('input', function() {
            this.classList.remove('input-error');
            
            if (this.value.length === 5) {
                const coloniasEncontradas = coloniasData[this.value];
                
                if (coloniasEncontradas && coloniasEncontradas.length > 0) {
                    coloniaDropdown.innerHTML = '';
                    coloniasEncontradas.forEach(col => {
                        const div = document.createElement('div');
                        div.className = 'dropdown-item';
                        div.textContent = col;
                        div.onclick = function() {
                            coloniaInput.value = col;
                            coloniaDropdown.classList.remove('show');
                        };
                        coloniaDropdown.appendChild(div);
                    });
                    coloniaDropdown.classList.add('show');
                    
                    if(!coloniasEncontradas.includes(coloniaInput.value)) {
                        coloniaInput.value = '';
                    }
                } else {
                    this.classList.add('input-error');
                    coloniaInput.value = '';
                    coloniaDropdown.innerHTML = '<div class="dropdown-item" style="color: #dc2626; font-weight: 600; cursor: default;">Código Postal fuera de cobertura</div>';
                    coloniaDropdown.classList.add('show');
                }
            } else {
                coloniaDropdown.classList.remove('show');
            }
        });

        document.addEventListener('click', function(e) {
            if (!coloniaInput.contains(e.target) && !coloniaDropdown.contains(e.target)) {
                coloniaDropdown.classList.remove('show');
            }
        });
        
        coloniaInput.addEventListener('focus', function() {
            if (coloniaDropdown.children.length > 0 && cpInput.value.length === 5) {
                coloniaDropdown.classList.add('show');
            }
        });
        
        coloniaInput.addEventListener('keydown', function(e) {
            e.preventDefault();
        });
    }
});