var cluj = { lat: 46.770008, lng: 23.590125 }
var initialZoom = 12
var mapElementName = 'map'
var mapTopPadding = '50px'

// One entry per Legenda/UTR tab. A locality is drawn from one or more plates, each
// with its own tile source and extent - Baciu's PUG comes as five separate sheets but
// is presented as a single tab. Adding a locality means adding an entry here and
// giving its markup a matching data-locality attribute in Index.html.
// Bounds are the warped extents reported by mapwarper.net/api/v1/{maps,layers}/<id>.
var localities = [
    {
        id: 'cluj',
        layers: [
            {
                tileUrl: 'https://mapwarper.net/mosaics/tile/869/{z}/{x}/{y}.png',
                bounds: { west: 23.492424, south: 46.681901, east: 23.775069, north: 46.878403 }
            }
        ]
    },
    {
        id: 'floresti',
        layers: [
            {
                tileUrl: 'https://mapwarper.net/maps/tile/110221/{z}/{x}/{y}.png',
                bounds: { west: 23.4428958, south: 46.7006942, east: 23.5412404, north: 46.7735126 }
            }
        ]
    },
    {
        id: 'baciu',
        layers: [
            {
                // Baciu
                tileUrl: 'https://mapwarper.net/maps/tile/110485/{z}/{x}/{y}.png',
                bounds: { west: 23.4669701, south: 46.776173, east: 23.5519751, north: 46.8150693 }
            },
            {
                // Corusu
                tileUrl: 'https://mapwarper.net/maps/tile/110487/{z}/{x}/{y}.png',
                bounds: { west: 23.480516, south: 46.8354363, east: 23.5181946, north: 46.8672193 }
            },
            {
                // Popesti
                tileUrl: 'https://mapwarper.net/maps/tile/110488/{z}/{x}/{y}.png',
                bounds: { west: 23.5112377, south: 46.802834, east: 23.5500514, north: 46.836888 }
            },
            {
                // Salistea Noua
                tileUrl: 'https://mapwarper.net/maps/tile/110490/{z}/{x}/{y}.png',
                bounds: { west: 23.4764526, south: 46.8626812, east: 23.4999941, north: 46.8805755 }
            },
            {
                // Mera, Radaia, Suceagu
                tileUrl: 'https://mapwarper.net/maps/tile/110493/{z}/{x}/{y}.png',
                bounds: { west: 23.4336002, south: 46.7701425, east: 23.4914099, north: 46.83031 }
            }
        ]
    },
    {
        id: 'apahida',
        layers: [
            {
                // Apahida
                tileUrl: 'https://mapwarper.net/maps/tile/111266/{z}/{x}/{y}.png',
                bounds: { west: 23.7184408, south: 46.77038, east: 23.7737552, north: 46.846541 }
            },
            {
                // Sannicoara (si Sub Coasta)
                tileUrl: 'https://mapwarper.net/maps/tile/111087/{z}/{x}/{y}.png',
                bounds: { west: 23.6849889, south: 46.7743611, east: 23.7610294, north: 46.813191 }
            },
            {
                // Dezmir
                tileUrl: 'https://mapwarper.net/maps/tile/111267/{z}/{x}/{y}.png',
                bounds: { west: 23.6851848, south: 46.7492618, east: 23.7490789, north: 46.7868384 }
            },
            {
                // Campenesti
                tileUrl: 'https://mapwarper.net/maps/tile/111268/{z}/{x}/{y}.png',
                bounds: { west: 23.634262, south: 46.8327783, east: 23.7486055, north: 46.8694435 }
            },
            {
                // Corpadea
                tileUrl: 'https://mapwarper.net/maps/tile/111269/{z}/{x}/{y}.png',
                bounds: { west: 23.8104626, south: 46.7805793, east: 23.8739716, north: 46.8183101 }
            },
            {
                // Pata (si Bodrog)
                tileUrl: 'https://mapwarper.net/maps/tile/111270/{z}/{x}/{y}.png',
                bounds: { west: 23.7169046, south: 46.7127197, east: 23.7799914, north: 46.7501777 }
            }
        ]
    },
    {
        id: 'feleacu',
        layers: [
            {
                // Feleacu
                tileUrl: 'https://mapwarper.net/maps/tile/111508/{z}/{x}/{y}.png',
                bounds: { west: 23.5799064, south: 46.6901630, east: 23.6564052, north: 46.7300605 }
            },
            {
                // Valcele (si Saradis)
                tileUrl: 'https://mapwarper.net/maps/tile/111518/{z}/{x}/{y}.png',
                bounds: { west: 23.6117891, south: 46.6654320, east: 23.6682281, north: 46.7152617 }
            },
            {
                // Gheorgheni
                tileUrl: 'https://mapwarper.net/maps/tile/111519/{z}/{x}/{y}.png',
                bounds: { west: 23.6582121, south: 46.7025632, east: 23.7138693, north: 46.7294237 }
            },
            {
                // Casele Micesti
                tileUrl: 'https://mapwarper.net/maps/tile/111520/{z}/{x}/{y}.png',
                bounds: { west: 23.5583361, south: 46.6866518, east: 23.5944070, north: 46.7087381 }
            }
        ]
    },
    {
        id: 'gilau',
        layers: [
            {
                // Gilau
                tileUrl: 'https://mapwarper.net/maps/tile/111709/{z}/{x}/{y}.png',
                bounds: { west: 23.3278708, south: 46.7402189, east: 23.4317613, north: 46.7785154 }
            },
            {
                // Somesu Rece - plansa 6.2a
                tileUrl: 'https://mapwarper.net/maps/tile/111699/{z}/{x}/{y}.png',
                bounds: { west: 23.3211550, south: 46.6943706, east: 23.3757983, north: 46.7438122 }
            },
            {
                // Somesu Rece - plansa 6.2b
                tileUrl: 'https://mapwarper.net/maps/tile/111706/{z}/{x}/{y}.png',
                bounds: { west: 23.2249869, south: 46.6637142, east: 23.3285109, north: 46.7021238 }
            },
            {
                // Somesu Cald
                tileUrl: 'https://mapwarper.net/maps/tile/111695/{z}/{x}/{y}.png',
                bounds: { west: 23.2626127, south: 46.7121026, east: 23.3445072, north: 46.7503330 }
            },
            {
                // Somesu Cald - detaliul din coltul plansei 6.3, la scara mai mare
                tileUrl: 'https://mapwarper.net/maps/tile/111698/{z}/{x}/{y}.png',
                bounds: { west: 23.2867630, south: 46.7072581, east: 23.3007370, north: 46.7137812 }
            }
        ]
    },
    {
        id: 'turda',
        layers: [
            {
                // Turda - plansa 8 Unitati teritoriale de referinta
                tileUrl: 'https://mapwarper.net/maps/tile/111710/{z}/{x}/{y}.png',
                bounds: { west: 23.7455068, south: 46.5414293, east: 23.8872834, north: 46.5941816 }
            },
            {
                // Petrilaca I (LR1) - detaliul din coltul plansei, desenat separat
                tileUrl: 'https://mapwarper.net/maps/tile/111722/{z}/{x}/{y}.png',
                bounds: { west: 23.8605210, south: 46.5746283, east: 23.8727950, north: 46.5816202 }
            },
            {
                // Petrilaca II (LR2) - detaliul din coltul plansei, desenat separat
                tileUrl: 'https://mapwarper.net/maps/tile/111723/{z}/{x}/{y}.png',
                bounds: { west: 23.8635036, south: 46.5648398, east: 23.8834674, north: 46.5727610 }
            }
        ]
    },
    {
        id: 'chinteni',
        layers: [
            {
                // Chinteni - reglementari urbanistice, unitati teritoriale de referinta (revizuire PUG 2023)
                tileUrl: 'https://mapwarper.net/maps/tile/111729/{z}/{x}/{y}.png',
                bounds: { west: 23.5025249, south: 46.8177108, east: 23.5841035, north: 46.8923814 }
            }
        ]
    },
    {
        id: 'gherla',
        layers: [
            {
                // Gherla - plansa 3 Situatie propusa, unitati teritoriale de referinta (reactualizare PUG 1998)
                tileUrl: 'https://mapwarper.net/maps/tile/111734/{z}/{x}/{y}.png',
                bounds: { west: 23.8669095, south: 47.0052648, east: 23.9499954, north: 47.0585802 }
            }
        ]
    },
    {
        id: 'dej',
        layers: [
            {
                // Dej si Somcutu Mic - plansa 3.0 Reglementari urbanistice - zonificare (reactualizare PUG 2009)
                tileUrl: 'https://mapwarper.net/maps/tile/111846/{z}/{x}/{y}.png',
                bounds: { west: 23.7156314, south: 47.0950358, east: 23.9415487, north: 47.1794315 }
            },
            {
                // Pintic - desenat pe plansa 3.0 intr-un chenar separat
                tileUrl: 'https://mapwarper.net/maps/tile/111847/{z}/{x}/{y}.png',
                bounds: { west: 23.7699493, south: 47.0639024, east: 23.8082238, north: 47.0846186 }
            }
        ]
    },
    {
        id: 'jucu',
        layers: [
            {
                // Jucu de Sus (resedinta de comuna) - plansa 6.1
                tileUrl: 'https://mapwarper.net/maps/tile/111909/{z}/{x}/{y}.png',
                bounds: { west: 23.7637560, south: 46.8180675, east: 23.8281837, north: 46.8889113 }
            },
            {
                // Visea - plansa 6.2
                tileUrl: 'https://mapwarper.net/maps/tile/111912/{z}/{x}/{y}.png',
                bounds: { west: 23.8622489, south: 46.8457900, east: 23.9019928, north: 46.8733808 }
            },
            {
                // Gadalin - plansa 6.3
                tileUrl: 'https://mapwarper.net/maps/tile/111911/{z}/{x}/{y}.png',
                bounds: { west: 23.8256458, south: 46.8138090, east: 23.8816835, north: 46.8595957 }
            },
            {
                // Jucu de Mijloc - plansa 6.4
                tileUrl: 'https://mapwarper.net/maps/tile/111908/{z}/{x}/{y}.png',
                bounds: { west: 23.7284932, south: 46.8245439, east: 23.8077068, north: 46.8631749 }
            },
            {
                // Jucu Herghelie - plansa 6.5
                tileUrl: 'https://mapwarper.net/maps/tile/111905/{z}/{x}/{y}.png',
                bounds: { west: 23.7509736, south: 46.8498450, east: 23.8069820, north: 46.8882570 }
            }
        ]
    },
    {
        id: 'bontida',
        layers: [
            {
                // Bontida (resedinta de comuna) - plansa 5.1
                tileUrl: 'https://mapwarper.net/maps/tile/112015/{z}/{x}/{y}.png',
                bounds: { west: 23.7766726, south: 46.8901963, east: 23.8340301, north: 46.9471023 }
            },
            {
                // Rascruci - plansa 5.2
                tileUrl: 'https://mapwarper.net/maps/tile/112017/{z}/{x}/{y}.png',
                bounds: { west: 23.7515744, south: 46.8708055, east: 23.8078991, north: 46.9252074 }
            },
            {
                // Coasta - plansa 5.3
                tileUrl: 'https://mapwarper.net/maps/tile/112018/{z}/{x}/{y}.png',
                bounds: { west: 23.8810267, south: 46.8735118, east: 23.9214424, north: 46.9002989 }
            },
            {
                // Tauseni - plansa 5.4
                tileUrl: 'https://mapwarper.net/maps/tile/112020/{z}/{x}/{y}.png',
                bounds: { west: 23.9019713, south: 46.8648854, east: 23.9412841, north: 46.8887904 }
            }
        ]
    },
    {
        id: 'ciurila',
        layers: [
            {
                // Ciurila (resedinta de comuna) - plansa 6.1
                tileUrl: 'https://mapwarper.net/maps/tile/112062/{z}/{x}/{y}.png',
                bounds: { west: 23.5147669, south: 46.6280834, east: 23.5707527, north: 46.6612277 }
            },
            {
                // Salicea - plansa 6.2
                tileUrl: 'https://mapwarper.net/maps/tile/112063/{z}/{x}/{y}.png',
                bounds: { west: 23.5107975, south: 46.6535811, east: 23.5946197, north: 46.6976631 }
            },
            {
                // Saliste - plansa 6.3
                tileUrl: 'https://mapwarper.net/maps/tile/112064/{z}/{x}/{y}.png',
                bounds: { west: 23.567004, south: 46.6367478, east: 23.6063665, north: 46.6639013 }
            },
            {
                // Prunis - plansa 6.4
                tileUrl: 'https://mapwarper.net/maps/tile/112065/{z}/{x}/{y}.png',
                bounds: { west: 23.5479745, south: 46.6183339, east: 23.5944638, north: 46.6456985 }
            },
            {
                // Padureni - plansa 6.5
                tileUrl: 'https://mapwarper.net/maps/tile/112066/{z}/{x}/{y}.png',
                bounds: { west: 23.5524138, south: 46.5992943, east: 23.5920132, north: 46.6188402 }
            },
            {
                // Sutu - plansa 6.6
                tileUrl: 'https://mapwarper.net/maps/tile/112067/{z}/{x}/{y}.png',
                bounds: { west: 23.5296502, south: 46.6076173, east: 23.5692714, north: 46.6270367 }
            },
            {
                // Filea de Jos - plansa 6.7
                tileUrl: 'https://mapwarper.net/maps/tile/112068/{z}/{x}/{y}.png',
                bounds: { west: 23.4873919, south: 46.6102775, east: 23.5431092, north: 46.6376197 }
            },
            {
                // Filea de Sus - plansa 6.8
                tileUrl: 'https://mapwarper.net/maps/tile/112069/{z}/{x}/{y}.png',
                bounds: { west: 23.4701619, south: 46.5984477, east: 23.5093845, north: 46.617928 }
            }
        ]
    },
    {
        id: 'garbau',
        layers: [
            {
                // Garbau (resedinta de comuna) - plansa 3.1
                tileUrl: 'https://mapwarper.net/maps/tile/112185/{z}/{x}/{y}.png',
                bounds: { west: 23.3285661, south: 46.8141824, east: 23.3819187, north: 46.8420024 }
            },
            {
                // Cornesti - plansa 3.2
                tileUrl: 'https://mapwarper.net/maps/tile/112188/{z}/{x}/{y}.png',
                bounds: { west: 23.3032658, south: 46.8771508, east: 23.3435543, north: 46.8963197 }
            },
            {
                // Nadaselu - plansa 3.3
                tileUrl: 'https://mapwarper.net/maps/tile/112181/{z}/{x}/{y}.png',
                bounds: { west: 23.401349, south: 46.8088023, east: 23.4297123, north: 46.8360182 }
            },
            {
                // Turea - plansa 3.4
                tileUrl: 'https://mapwarper.net/maps/tile/112186/{z}/{x}/{y}.png',
                bounds: { west: 23.3410063, south: 46.8418433, east: 23.3803189, north: 46.8609151 }
            },
            {
                // Vistea - plansa 3.5
                tileUrl: 'https://mapwarper.net/maps/tile/112184/{z}/{x}/{y}.png',
                bounds: { west: 23.3787523, south: 46.7916647, east: 23.4347265, north: 46.819034 }
            }
        ]
    },
    {
        id: 'cojocna',
        layers: [
            {
                // Cojocna (resedinta de comuna) - plansa R/1
                tileUrl: 'https://mapwarper.net/maps/tile/112242/{z}/{x}/{y}.png',
                bounds: { west: 23.8032208, south: 46.7307682, east: 23.9112828, north: 46.7610282 }
            },
            {
                // Boju - plansa R/2
                tileUrl: 'https://mapwarper.net/maps/tile/112246/{z}/{x}/{y}.png',
                bounds: { west: 23.7647365, south: 46.7014353, east: 23.8278743, north: 46.720994 }
            },
            {
                // Cara - plansa R/3
                tileUrl: 'https://mapwarper.net/maps/tile/112245/{z}/{x}/{y}.png',
                bounds: { west: 23.7578392, south: 46.747807, east: 23.8371097, north: 46.7679583 }
            },
            {
                // Iuriu de Campie - plansa R/4
                tileUrl: 'https://mapwarper.net/maps/tile/112248/{z}/{x}/{y}.png',
                bounds: { west: 23.8987633, south: 46.6902215, east: 23.9590204, north: 46.7103397 }
            },
            {
                // Boj Catun - plansa R/5
                tileUrl: 'https://mapwarper.net/maps/tile/112247/{z}/{x}/{y}.png',
                bounds: { west: 23.8143736, south: 46.6870339, east: 23.888113, north: 46.7074863 }
            },
            {
                // Moristi - plansa R/6
                tileUrl: 'https://mapwarper.net/maps/tile/112244/{z}/{x}/{y}.png',
                bounds: { west: 23.7688786, south: 46.7613059, east: 23.8363748, north: 46.7942159 }
            },
            {
                // Straja si Huci - plansa R/7
                tileUrl: 'https://mapwarper.net/maps/tile/112249/{z}/{x}/{y}.png',
                bounds: { west: 23.8492437, south: 46.6576807, east: 23.9488734, north: 46.7208635 }
            }
        ]
    },
    {
        id: 'iclod',
        layers: [
            {
                // Iclod (resedinta de comuna) - plansa 1.2
                tileUrl: 'https://mapwarper.net/maps/tile/113977/{z}/{x}/{y}.png',
                bounds: { west: 23.7844208, south: 46.9642586, east: 23.8445221, north: 47.0022979 }
            },
            {
                // Iclozel - plansa 2.2
                tileUrl: 'https://mapwarper.net/maps/tile/113978/{z}/{x}/{y}.png',
                bounds: { west: 23.8072731, south: 46.9549702, east: 23.8464021, north: 46.9928378 }
            },
            {
                // Livada - plansa 3.2
                tileUrl: 'https://mapwarper.net/maps/tile/113980/{z}/{x}/{y}.png',
                bounds: { west: 23.8157631, south: 46.9801677, east: 23.8608652, north: 47.0166359 }
            },
            {
                // Orman - plansa 4.2
                tileUrl: 'https://mapwarper.net/maps/tile/113981/{z}/{x}/{y}.png',
                bounds: { west: 23.7964342, south: 47.0285077, east: 23.8361665, north: 47.0666454 }
            },
            {
                // Fundatura - plansa 5.2
                tileUrl: 'https://mapwarper.net/maps/tile/113979/{z}/{x}/{y}.png',
                bounds: { west: 23.7552502, south: 46.9374562, east: 23.8092348, north: 46.9753707 }
            }
        ]
    }
]

var selectedLocality = null

// The map shows either the PUG plates or the PUZ plates; the switch in the top bar
// picks which. overlayOpacity is shared, so the slider keeps its setting across it.
var planMode = 'pug';
var overlayOpacity = 0.7;
var theMap = null;
var pugOverlays = [];

function initMapElementToCluj() {
    var map = getMapCenteredOnCluj();
    theMap = map;

    addPaddingDivToMap(map, 0, google.maps.ControlPosition.TOP_LEFT)
    addPaddingDivToMap(map, 0, google.maps.ControlPosition.TOP_RIGHT)

    localities.forEach(function (locality) {
        locality.layers.forEach(function (layer) {
            pugOverlays.push(getMapTiles(getTileUrlProvider(layer)));
        });
    });

    addSlideControlToMap(map, google.maps.ControlPosition.BOTTOM_CENTER);
    followVisibleLocalities(map);
    watchPuz(map);
    setPlanMode(planMode);
}

function getMapCenteredOnCluj() {
    var mapOptions = {
        zoom: initialZoom,
        center: cluj,
        scaleControl: true,
        mapTypeControlOptions: {
            position: google.maps.ControlPosition.LEFT_TOP
        }
    }
    return new google.maps.Map(document.getElementById(mapElementName), mapOptions);
}

function getMapTiles(tileUrlProvider) {
    return new google.maps.ImageMapType({
        getTileUrl: tileUrlProvider,
        tileSize: new google.maps.Size(256, 256),
        maxZoom: 25,
        minZoom: 0,
        opacity: overlayOpacity
    });
}

// Returning null from getTileUrl tells Google Maps to skip the request, so mapwarper
// is only ever asked for tiles the plate actually covers.
function getTileUrlProvider(layer) {
    return function (coord, zoom) {
        if (!tileIntersectsBounds(coord, zoom, layer.bounds)) {
            return null;
        }
        return layer.tileUrl
            .replace('{z}', zoom)
            .replace('{x}', coord.x)
            .replace('{y}', coord.y);
    };
}

function tileIntersectsBounds(coord, zoom, bounds) {
    return coord.x >= lngToTileX(bounds.west, zoom)
        && coord.x <= lngToTileX(bounds.east, zoom)
        && coord.y >= latToTileY(bounds.north, zoom)
        && coord.y <= latToTileY(bounds.south, zoom);
}

function lngToTileX(lng, zoom) {
    return Math.floor((lng + 180) / 360 * Math.pow(2, zoom));
}

function latToTileY(lat, zoom) {
    var rad = lat * Math.PI / 180;
    return Math.floor((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2 * Math.pow(2, zoom));
}

function addPaddingDivToMap(map, index, position) {
    var paddingDiv = document.createElement('div');
    paddingDiv.style.height = mapTopPadding;
    paddingDiv.style.width = mapTopPadding;
    paddingDiv.index = index;
    map.controls[position].push(paddingDiv);
}

function addSlideControlToMap(map, position) {
    var slideControlDiv = document.createElement('div');
    slideControlDiv.style.width = '75%';
    slideControlDiv.style.marginBottom = '50px';
    SlideControl(slideControlDiv);

    slideControlDiv.index = 1;
    map.controls[position].push(slideControlDiv);
}

function SlideControl(controlDiv) {

    var slideBar = document.createElement('input');
    slideBar.type = 'range';
    slideBar.min = '0';
    slideBar.max = '100';
    slideBar.value = String(Math.round(overlayOpacity * 100));
    slideBar.className = 'slider';

    controlDiv.appendChild(slideBar);

    slideBar.addEventListener('input', function () {
        setOverlayOpacity(this.value / 100);
    });
}

function setOverlayOpacity(opacity) {
    overlayOpacity = opacity;
    pugOverlays.forEach(function (overlay) {
        overlay.setOpacity(opacity);
    });
    puzOverlays.forEach(function (item) {
        if (item.image) {
            item.image.setOpacity(opacity);
        }
    });
}

// --- PUG / PUZ switch ---------------------------------------------------------
// PUZ-uri come from puz/puz.json, written by tools/puz/puz.py from the recipes in
// puzuri/. Each plate is already warped to Web Mercator, so a GroundOverlay over its
// bounds lines up exactly; its boundary comes from the plate's coordinate inventory.

var puzList = [];
var puzOverlays = [];   // { puz, outline: Polygon, image: GroundOverlay, created when first needed }
var puzInfoWindow = null;
var puzState = 'none';  // 'none' -> 'loading' -> 'ready'
var PUZ_COLOR = '#d6007e';
// Plates are only fetched for PUZ-uri in view from this zoom on; below it a plate
// is a few pixels wide and the outline says as much. Outlines are always drawn.
var PUZ_IMAGE_MIN_ZOOM = 15;
var MONTHS = ['ianuarie', 'februarie', 'martie', 'aprilie', 'mai', 'iunie', 'iulie',
    'august', 'septembrie', 'octombrie', 'noiembrie', 'decembrie'];

function setPlanMode(mode) {
    planMode = mode === 'puz' ? 'puz' : 'pug';
    if (document.body) {
        document.body.classList.toggle('mode-puz', planMode === 'puz');
    }
    eachElement('.plan-toggle [data-plan]', function (button) {
        var isOn = button.dataset.plan === planMode;
        button.classList.toggle('active', isOn);
        button.setAttribute('aria-pressed', isOn);
    });
    if (!theMap) {
        return;
    }

    if (planMode === 'puz') {
        loadPuz();
    }

    // Hidden PUG plates are taken off the map rather than made transparent, so their
    // tiles stop loading.
    theMap.overlayMapTypes.clear();
    if (planMode === 'pug') {
        pugOverlays.forEach(function (overlay) { theMap.overlayMapTypes.push(overlay); });
    }
    puzOverlays.forEach(function (item) {
        item.outline.setMap(planMode === 'puz' ? theMap : null);
    });
    syncPuzImages();
    if (puzInfoWindow) {
        puzInfoWindow.close();
    }
    updatePuzLegend();
}

// Puts on the map the plates of the PUZ-uri in view and takes off the rest, so the
// number of PUZ-uri on the site does not decide how much a visitor downloads.
// A plate taken off stays in the browser's cache for when it comes back into view.
//
// Where two PUZ-uri overlap, the later one is what applies, so it must be drawn on
// top. Ground overlays stack in the order they are added and puz.json lists the
// newest first; so whenever the set in view changes, the plates in view are re-added
// oldest first.
function syncPuzImages() {
    if (!theMap) {
        return;
    }
    var viewport = theMap.getBounds();
    var showPlates = planMode === 'puz' && viewport && theMap.getZoom() >= PUZ_IMAGE_MIN_ZOOM;
    var wanted = puzOverlays.filter(function (item) {
        return showPlates && viewport.intersects(toLatLngBounds(item.puz.bounds));
    });
    var changed = puzOverlays.some(function (item) {
        var onMap = !!(item.image && item.image.getMap());
        return onMap !== (wanted.indexOf(item) >= 0);
    });
    if (!changed) {
        return;
    }
    puzOverlays.forEach(function (item) {
        if (item.image && item.image.getMap()) {
            item.image.setMap(null);
        }
    });
    wanted.slice().reverse().forEach(function (item) {
        ensurePuzImage(item);
        item.image.setMap(theMap);
    });
}

function ensurePuzImage(item) {
    if (item.image) {
        return;
    }
    item.image = new google.maps.GroundOverlay(item.puz.imagine, toLatLngBounds(item.puz.bounds), {
        opacity: overlayOpacity,
        clickable: true
    });
    item.image.addListener('click', function (event) { openPuzInfo(item.puz, event.latLng); });
}

// puz.json is only fetched the first time PUZ mode is switched on, so visitors who
// stay on the PUG never download it.
function loadPuz() {
    if (puzState !== 'none') {
        return;
    }
    puzState = 'loading';
    fetch('puz/puz.json')
        .then(function (response) { return response.ok ? response.json() : []; })
        .catch(function () { return []; })
        .then(function (list) {
            puzState = 'ready';
            puzList = list;
            puzOverlays = list.map(createPuzOverlay);
            setPlanMode(planMode);
            if (requestedPuz) {
                showPuz(requestedPuz);
            }
        });
}

function watchPuz(map) {
    map.addListener('idle', function () {
        syncPuzImages();
        updatePuzLegend();
    });
    // A PUZ is a few hundred metres at most, so at city zoom its outline would be a
    // speck; a thicker stroke keeps it findable until the plate itself is legible.
    map.addListener('zoom_changed', function () {
        var weight = map.getZoom() < 16 ? 6 : 2;
        puzOverlays.forEach(function (item) { item.outline.setOptions({ strokeWeight: weight }); });
    });
}

// The list is newest first; later PUZ-uri get higher outlines, so a click where two
// overlap opens the one that applies.
function createPuzOverlay(puz, index, list) {
    var outline = new google.maps.Polygon({
        paths: puz.limita.map(function (p) { return { lat: p[1], lng: p[0] }; }),
        strokeColor: PUZ_COLOR,
        strokeOpacity: 0.9,
        strokeWeight: theMap && theMap.getZoom() >= 16 ? 2 : 6,
        fillColor: PUZ_COLOR,
        fillOpacity: 0.06,
        zIndex: 2 + (list ? list.length - index : 0)
    });
    outline.addListener('click', function (event) { openPuzInfo(puz, event.latLng); });
    return { puz: puz, outline: outline, image: null };
}

function openPuzInfo(puz, position) {
    if (!puzInfoWindow) {
        puzInfoWindow = new google.maps.InfoWindow({ maxWidth: 360 });
    }
    puzInfoWindow.setContent(
        '<div class="puz-info">' +
        '<strong>HCL ' + escapeHtml(puz.hcl) + '</strong> &middot; ' + escapeHtml(formatDate(puz.data)) + '<br>' +
        escapeHtml(puz.titlu) + '<br>' +
        utrSummaryHtml(puz) +
        'Suprafață reglementată: ' + puz.suprafata_m2.toLocaleString('ro-RO') + ' m&sup2;' +
        decisionNotesHtml(puz) +
        '<a href="' + escapeHtml(puz.pdf) + '" target="_blank" rel="noopener">Hotărârea și anexele (PDF)</a>' +
        '</div>');
    puzInfoWindow.setPosition(position);
    puzInfoWindow.open(theMap);
}

// What the decision's text says beyond the plate: how long the PUZ is valid, which
// other PUZ it amends or was amended by, where the text overrides the drawing (the
// council can amend a PUZ in session without the plate changing), and the
// conditions and obligations it sets. Expired PUZ-uri stay on the map; the date says so.
function decisionNotesHtml(puz) {
    return approximateHtml(puz) + validityHtml(puz) + amendmentsHtml(puz) + differencesHtml(puz) + conditionsHtml(puz);
}

// Plates without usable coordinates are placed on OpenStreetMap streets and buildings;
// say how far off they may be.
function approximateHtml(puz) {
    var g = puz.georeferentiere;
    return g && g.aproximativ
        ? '<div class="puz-approx">Poziționare aproximativă (±' + escapeHtml(g.precizie_m) +
          ' m), după străzi și clădiri din OpenStreetMap: planșa nu are coordonate utilizabile.</div>'
        : '';
}

function validityHtml(puz) {
    var v = puz.valabilitate;
    if (!v || !v.pana_la) {
        return '';
    }
    var expired = v.pana_la < todayIso();
    var text = (expired ? 'Valabilitate expirată la ' : 'Valabil până la ') + formatDate(v.pana_la);
    var extensions = (v.prelungiri || []).map(function (p) { return 'HCL ' + p.hcl; });
    return '<div class="puz-valid' + (expired ? ' puz-expired' : '') + '">' + escapeHtml(text) +
        (v.ani && !extensions.length ? ' <span class="puz-muted">(' + v.ani + ' ani de la aprobare)</span>' : '') +
        (extensions.length ? ' <span class="puz-muted">(prelungit prin ' + escapeHtml(extensions.join(', ')) + ')</span>' : '') +
        '</div>';
}

// `modificat_de` entries are a decision number, or {hcl, data, rezumat, plansa_noua}
// when the amendment changed something worth saying.
function amendmentsHtml(puz) {
    var html = '';
    if (puz.modifica && puz.modifica.length) {
        html += '<div class="puz-mod">Modifică PUZ-ul aprobat prin HCL ' + escapeHtml(puz.modifica.join(', ')) + '</div>';
    }
    (puz.modificat_de || []).forEach(function (m) {
        if (typeof m === 'string') {
            html += '<div class="puz-mod">Modificat prin HCL ' + escapeHtml(m) + '</div>';
            return;
        }
        html += '<div class="puz-mod"><strong>Modificat prin HCL ' + escapeHtml(m.hcl) + '</strong>' +
            (m.data ? ' (' + escapeHtml(formatDate(m.data)) + ')' : '') +
            (m.plansa_noua ? ' &ndash; planșa afișată e cea din modificare' : '') +
            (m.rezumat ? ': ' + escapeHtml(m.rezumat) : '') + '</div>';
    });
    return html;
}

function differencesHtml(puz) {
    var items = puz.diferente_fata_de_plansa || [];
    return items.length
        ? '<div class="puz-diff"><strong>Textul hotărârii diferă de planșă:</strong>' + itemsHtml(items) + '</div>'
        : '';
}

function conditionsHtml(puz) {
    var items = puz.conditii || [];
    return items.length
        ? '<details class="puz-cond"><summary>Condiții și obligații din hotărâre (' + items.length + ')</summary>' +
          itemsHtml(items) + '</details>'
        : '';
}

function itemsHtml(items) {
    return '<ul>' + items.map(function (item) { return '<li>' + escapeHtml(item) + '</li>'; }).join('') + '</ul>';
}

function todayIso() {
    var d = new Date();
    return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
}

function utrSummaryHtml(puz) {
    return (puz.utr || []).map(function (utr) {
        var parts = ['UTR <strong>' + escapeHtml(utr.cod) + '</strong> &ndash; ' + escapeHtml(utr.denumire)];
        if (utr.pot_max) { parts.push('POT max. ' + escapeHtml(utr.pot_max)); }
        if (utr.cut_max) { parts.push('CUT max. ' + escapeHtml(utr.cut_max)); }
        if (utr.h_max) { parts.push('H max. ' + escapeHtml(utr.h_max)); }
        return parts.join(' &middot; ') + '<br>';
    }).join('');
}

// The Legenda section lists the PUZ-uri in view, each with the legend cropped from
// its own plate: designers draw their own symbols, so there is no common legend.
function updatePuzLegend() {
    var list = document.getElementById('puz-legend-list');
    var note = document.getElementById('puz-legend-note');
    if (!list || !note || planMode !== 'puz') {
        return;
    }
    var viewport = theMap && theMap.getBounds();
    var visible = puzList.filter(function (puz) {
        return viewport && viewport.intersects(toLatLngBounds(puz.bounds));
    });
    // Legend images follow the plates: only for PUZ-uri in view, and only once the
    // map is close enough to show their plates. Otherwise a short list to pick from.
    var detailed = theMap && theMap.getZoom() >= PUZ_IMAGE_MIN_ZOOM;
    var shown = visible;
    if (puzState !== 'ready') {
        note.textContent = 'Se încarcă PUZ-urile…';
    } else if (puzList.length === 0) {
        note.textContent = 'Nu a fost adăugat încă niciun PUZ.';
    } else if (visible.length === 0) {
        note.textContent = 'Niciun PUZ în zona vizibilă a hărții. Mai jos, toate cele ' + puzCount(puzList.length)
            + ' adăugate până acum.';
        shown = puzList;
        detailed = false;
    } else {
        note.textContent = capitalize(puzCount(visible.length)) + ' în zona vizibilă a hărții.'
            + (detailed ? '' : ' Apropie harta ca să vezi planșele și legendele lor.');
    }
    var key = (detailed ? 'card:' : 'list:') + shown.map(function (puz) { return puz.id; }).join(',');
    if (list.dataset.key === key) {
        return;
    }
    list.dataset.key = key;
    list.innerHTML = shown.map(detailed ? puzCardHtml : puzListItemHtml).join('');
}

function puzListItemHtml(puz) {
    return '<div class="puz-list-item"><strong>HCL ' + escapeHtml(puz.hcl) + '</strong> &ndash; ' +
        escapeHtml(puz.titlu) + ' &middot; <a href="#map" data-puz-zoom="' + escapeHtml(puz.id) + '">Arată pe hartă</a></div>';
}

// "un PUZ", "5 PUZ-uri", "20 de PUZ-uri", "101 PUZ-uri"
function puzCount(n) {
    if (n === 1) {
        return 'un PUZ';
    }
    var lastTwo = n % 100;
    return n + (lastTwo === 0 || lastTwo >= 20 ? ' de' : '') + ' PUZ-uri';
}

function capitalize(text) {
    return text.charAt(0).toUpperCase() + text.slice(1);
}

function puzCardHtml(puz) {
    return '<div class="puz-card">' +
        '<h3 class="puz-card-title">HCL ' + escapeHtml(puz.hcl) +
        ' <small class="text-muted">' + escapeHtml(formatDate(puz.data)) + '</small></h3>' +
        '<p>' + escapeHtml(puz.titlu) + '</p>' +
        '<p class="puz-card-utr">' + utrSummaryHtml(puz) + '</p>' +
        decisionNotesHtml(puz) +
        (puz.legenda
            ? '<img class="puz-legend-image" loading="lazy" src="' + escapeHtml(puz.legenda) +
              '" alt="Legenda planșei de reglementări, HCL ' + escapeHtml(puz.hcl) + '" />'
            : '') +
        '<p class="puz-card-links">' +
        '<a href="#map" data-puz-zoom="' + escapeHtml(puz.id) + '">Arată pe hartă</a> &middot; ' +
        '<a href="' + escapeHtml(puz.pdf) + '" target="_blank" rel="noopener">Hotărârea și anexele (PDF)</a>' +
        (puz.pagina ? ' &middot; <a href="' + escapeHtml(puz.pagina) + '" target="_blank" rel="noopener">Pagina hotărârii</a>' : '') +
        '</p></div>';
}

// Zooms to a PUZ and opens its details, from a legend card or a ?puz=<id> link.
function showPuz(id) {
    var puz = puzList.filter(function (p) { return p.id === id; })[0];
    if (puz && theMap) {
        var bounds = toLatLngBounds(puz.bounds);
        theMap.fitBounds(bounds);
        openPuzInfo(puz, bounds.getCenter());
    }
}

// ?plan=puz opens on the PUZ plates; ?puz=<id> also zooms to that PUZ and opens it.
var requestedPuz = new URLSearchParams(window.location.search).get('puz');

function initPlanToggle() {
    var requested = new URLSearchParams(window.location.search).get('plan');
    if (requested || requestedPuz) {
        planMode = requested === 'pug' ? 'pug' : 'puz';
    }
    eachElement('.plan-toggle [data-plan]', function (button) {
        button.addEventListener('click', function () {
            setPlanMode(button.dataset.plan);
        });
    });
    document.addEventListener('click', function (event) {
        var link = event.target.closest && event.target.closest('[data-puz-zoom]');
        if (link) {
            showPuz(link.dataset.puzZoom);
        }
    });
    setPlanMode(planMode);
}

function formatDate(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
    return m ? parseInt(m[3], 10) + ' ' + MONTHS[parseInt(m[2], 10) - 1] + ' ' + m[1] : (iso || '');
}

function escapeHtml(text) {
    return String(text == null ? '' : text).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
}

// --- Legenda / UTR tabs -----------------------------------------------------
// What you can see on the map decides which localities are on offer below it.

function followVisibleLocalities(map) {
    map.addListener('idle', function () {
        var viewport = map.getBounds();
        if (!viewport) {
            return;
        }
        showTabsFor(localities.filter(function (locality) {
            return locality.layers.some(function (layer) {
                return viewport.intersects(toLatLngBounds(layer.bounds));
            });
        }));
    });
}

function toLatLngBounds(bounds) {
    return new google.maps.LatLngBounds(
        new google.maps.LatLng(bounds.south, bounds.west),
        new google.maps.LatLng(bounds.north, bounds.east));
}

// Panning away from every plate would leave Legenda and UTR-uri empty, so an empty
// result falls back to offering all of them rather than none.
function showTabsFor(visibleLocalities) {
    var visible = visibleLocalities.length > 0 ? visibleLocalities : localities;
    var ids = visible.map(function (locality) { return locality.id; });

    eachElement('.locality-tab', function (tab) {
        tab.parentNode.hidden = ids.indexOf(tab.dataset.locality) < 0;
    });

    if (ids.indexOf(selectedLocality) < 0) {
        selectLocality(ids[0]);
    }
}

function selectLocality(id) {
    selectedLocality = id;

    eachElement('.locality-tab', function (tab) {
        var isSelected = tab.dataset.locality === id;
        tab.classList.toggle('active', isSelected);
        tab.setAttribute('aria-selected', isSelected);
    });

    eachElement('.locality-pane', function (pane) {
        pane.hidden = pane.dataset.locality !== id;
    });
}

function initLocalityTabs() {
    eachElement('.locality-tab', function (tab) {
        tab.addEventListener('click', function (event) {
            event.preventDefault();
            selectLocality(tab.dataset.locality);
        });
    });
    selectLocality(localities[0].id);
}

function eachElement(selector, callback) {
    Array.prototype.forEach.call(document.querySelectorAll(selector), callback);
}

document.addEventListener('DOMContentLoaded', initLocalityTabs);
document.addEventListener('DOMContentLoaded', initPlanToggle);
