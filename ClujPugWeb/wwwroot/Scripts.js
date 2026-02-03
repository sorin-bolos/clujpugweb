var cluj = { lat: 46.770008, lng: 23.590125 }
var initialZoom = 12
var mapElementName = 'map'
var mapTopPadding = '50px'

function initMapElementToCluj() {
    var map = getMapCenteredOnCluj();

    addPaddingDivToMap(map, 0, google.maps.ControlPosition.TOP_LEFT)
    addPaddingDivToMap(map, 0, google.maps.ControlPosition.TOP_RIGHT)

    var pugMap = getMapTiles(getPugTileUrl);

    map.overlayMapTypes.insertAt(0, pugMap);

    addSlideControlToMap(map, pugMap, google.maps.ControlPosition.BOTTOM_CENTER);
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

function getPugTileUrl(coord, zoom) {
    return "https://mapwarper.net/mosaics/tile/869/" +
           zoom + "/" + coord.x + "/" + coord.y + ".png";
    //return "https://clujpug.ro/tiles/" +
    //       zoom + "_" + coord.x + "_" + coord.y + ".png";
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

function SlideControl(controlDiv, overlayMap) {

    var slideBar = document.createElement('input');
    slideBar.type = 'range';
    slideBar.min = '0';
    slideBar.max = '100';
    slideBar.value = '70';
    slideBar.className = 'slider';

    controlDiv.appendChild(slideBar);

    slideBar.addEventListener('input', function () {
        overlayMap.setOpacity(this.value / 100);
    });
}
