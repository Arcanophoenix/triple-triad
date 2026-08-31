(function() {
	 var default_eorzeadb = {
		cdn_prefix: 'https://lds-img.finalfantasyxiv.com/',
		version_js_uri: 'https://lds-img.finalfantasyxiv.com/pc/global/js/eorzeadb/version.js',
		dynamic_tooltip: false
	};
	if ( typeof eorzeadb == "undefined" ) {
		eorzeadb = default_eorzeadb;
	}
	else {
		for (var property in default_eorzeadb) {
			if ( typeof eorzeadb[property] === "undefined" ) {
				eorzeadb[property] = default_eorzeadb[property];
			}
		}
	}

	var version_refresh_interval = 60;
	var refresh_time = Math.floor(new Date().getTime() / 1000 / version_refresh_interval) * version_refresh_interval;

	window.recieve_eorzeadb_version = function(data) {
		eorzeadb.versions = data;
	};

	var counter = 0;
	function after_load() {
		counter++;
		if ( counter >= 2 ) {
			eorzeadb.init();
		}
	}

	external_load('js', eorzeadb.version_js_uri + '?' + refresh_time, function() {
		external_load('css', eorzeadb.cdn_prefix + 'pc/global/css/eorzeadb_external.css?' + eorzeadb.versions.css, after_load);
		external_load('js', eorzeadb.cdn_prefix + 'pc/global/js/eorzeadb/main.js?' + eorzeadb.versions.js, after_load);
	});

	function external_load(type, src, callback){
		var el, src_attr;
		var d = document;
		if ( type === 'js' ) {
			el = d.createElement('script');
			el.type  = 'text/javascript';
			src_attr = 'src';
		}
		else if ( type === 'css' ) {
			el = d.createElement('link');
			el.type  = 'text/css';
			el.rel   = 'stylesheet';
			src_attr = 'href';
		}
		el.async = true;
		if (window.ActiveXObject) {
			el.onreadystatechange = function() {
				var state = el.readyState;
				if ( state === 'loaded' || state === 'complete' ) {
					callback();
				}
			};
		}
		else {
			el.onload = callback;
		}
		el[src_attr] = src;
		var head = d.getElementsByTagName("head")[0] || d.documentElement;
		head.insertBefore(el, head.firstChild);
	}
})();
