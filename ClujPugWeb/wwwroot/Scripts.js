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
    }
]

var selectedLocality = null

function initMapElementToCluj() {
    var map = getMapCenteredOnCluj();

    addPaddingDivToMap(map, 0, google.maps.ControlPosition.TOP_LEFT)
    addPaddingDivToMap(map, 0, google.maps.ControlPosition.TOP_RIGHT)

    var overlays = [];
    localities.forEach(function (locality) {
        locality.layers.forEach(function (layer) {
            var overlay = getMapTiles(getTileUrlProvider(layer));
            map.overlayMapTypes.insertAt(overlays.length, overlay);
            overlays.push(overlay);
        });
    });

    addSlideControlToMap(map, overlays, google.maps.ControlPosition.BOTTOM_CENTER);
    followVisibleLocalities(map);
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
        opacity: 0.7
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

function addSlideControlToMap(map, overlayMapTypes, position) {
    var slideControlDiv = document.createElement('div');
    slideControlDiv.style.width = '75%';
    slideControlDiv.style.marginBottom = '50px';
    var slideControl = new SlideControl(slideControlDiv, overlayMapTypes);

    slideControlDiv.index = 1;
    map.controls[position].push(slideControlDiv);
}

function SlideControl(controlDiv, overlayMaps) {

    var slideBar = document.createElement('input');
    slideBar.type = 'range';
    slideBar.min = '0';
    slideBar.max = '100';
    slideBar.value = '70';
    slideBar.className = 'slider';

    controlDiv.appendChild(slideBar);

    slideBar.addEventListener('input', function () {
        var opacity = this.value / 100;
        overlayMaps.forEach(function (overlayMap) {
            overlayMap.setOpacity(opacity);
        });
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
