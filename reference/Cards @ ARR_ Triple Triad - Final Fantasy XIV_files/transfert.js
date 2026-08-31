$(document).ready(function() {
	$('#top').click(function() {
		$('html, body').animate({ scrollTop: 0 }, 'slow');
		return false;
	});
	$('#bottom').click(function() {
		$('html, body').animate({ scrollTop: $(document).height() }, 'slow');
		return false;
	});
});

function supports_html5_storage() {
	try {
		return 'localStorage' in window && window['localStorage'] !== null;
	} catch (e) {
		return false;
	}
}

function transfertCollection() {
	var possessedCards = [];

	if (supports_html5_storage()) {
		if (localStorage.getItem('arr_cards_collection') != null) {
			possessedCards = JSON.parse(localStorage.getItem('arr_cards_collection'));
		}
	} else {
		if ($.cookie('arr_cards_collection') != undefined) {
			possessedCards = JSON.parse($.cookie('arr_cards_collection'));
		}
	}
	
	saveCollection(possessedCards);
}

function saveCollection(possessedCards) {
	var lang = 'en';
	if ($.cookie('arrtt_lang') != undefined) {
		lang = $.cookie('arrtt_lang');
	}

	var url = 'http://arrtripletriad.com/transfer' + (lang == 'fr' ? 't' : '');
	var form = $('<form style="display: none;" action="' + url + '" method="post">' +
	  '<input type="text" name="cards" value="' + JSON.stringify(possessedCards) + '" />' +
	  '</form>');
	$('body').append(form);
	form.submit();
}