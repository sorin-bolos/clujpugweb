var cluj = { lat: 46.770008, lng: 23.590125 }
var initialZoom = 12
var mapElementName = 'map'
var mapTopPadding = '50px'

// One entry per PUG overlay. Adding a village means adding an entry here and giving
// its Legenda/UTR markup a matching data-locality attribute in Index.html.
// Bounds are the warped extents reported by mapwarper.net/api/v1/{maps,layers}/<id>.
var localities = [
    {
        id: 'cluj',
        tileUrl: 'https://mapwarper.net/mosaics/tile/869/{z}/{x}/{y}.png',
        bounds: { west: 23.492424, south: 46.681901, east: 23.775069, north: 46.878403 }
    },
    {
        id: 'floresti',
        tileUrl: 'https://mapwarper.net/maps/tile/110221/{z}/{x}/{y}.png',
        bounds: { west: 23.4428958, south: 46.7006942, east: 23.5412404, north: 46.7735126 }
    }
]

var selectedLocality = null

function initMapElementToCluj() {
    var map = getMapCenteredOnCluj();

    addPaddingDivToMap(map, 0, google.maps.ControlPosition.TOP_LEFT)
    addPaddingDivToMap(map, 0, google.maps.ControlPosition.TOP_RIGHT)

    var overlays = localities.map(function (locality, index) {
        var overlay = getMapTiles(getTileUrlProvider(locality));
        map.overlayMapTypes.insertAt(index, overlay);
        return overlay;
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
function getTileUrlProvider(locality) {
    return function (coord, zoom) {
        if (!tileIntersectsBounds(coord, zoom, locality.bounds)) {
            return null;
        }
        return locality.tileUrl
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
            return viewport.intersects(toLatLngBounds(locality.bounds));
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
