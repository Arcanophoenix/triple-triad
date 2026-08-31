$('document').ready(function() {
	$('.showHideItem').hide();
	$('.showHideBlock').click(function() { showHideBlock(this); });
	
	if (typeof getLocal('arrtt_cookie_accepted') == 'undefined' || getLocal('arrtt_cookie_accepted') == null) {
		$('#cookiePermission').show();
	}
	
	$('#cookiePermClose').click(function() {
		setLocal('arrtt_cookie_accepted', 'true');
		document.location.reload(true);
	});
	
	$('#langSelectLabel').click(function() {
		$('#langSelectList').toggle();
	});
});

function showMessagePopup (message = '') {
	if (message != '') {
		$('#messagePopup span').empty().append(message);
	}
	
	$('#messagePopup').show();
}

function hideMessagePopup() {
	$('#messagePopup').hide();
}

// Checking if the browser supports local storage
function supports_html5_storage() {
	try {
		return 'localStorage' in window && window['localStorage'] !== null;
	} catch (e) {
		return false;
	}
}

function setLocal(key, value) {
	if (supports_html5_storage()) {
		localStorage.setItem(key, value);
	} else {
		$.cookie(key, value);
	}
}

function getLocal(key) {
	if (supports_html5_storage()) {
		return localStorage.getItem(key);
	} else {
		return $.cookie(key);
	}
}

function removeLocal(key) {
	if (supports_html5_storage()) {
		localStorage.removeItem(key);
	} else {
		$.cookie(key, null);
	}
}

function showHideBlock(elem) {
	let item = $(elem).prop('class').split(' ')[1];
	$('.showHideItem.' + item).toggle();
}