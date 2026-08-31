(function() {
	var eorzeadb_klass = {
		cdn_prefix: 'https://img.finalfantasyxiv.com/lds/',
		versions: {data: 0, js: 0, css: 0},
		dynamic_tooltip: false,
		is_tooltip_show: false,
		popup_contents: {},
		popup_content_last_key: null,
		$tooltip: null,
		_hide_timer: null,
		pushup: function(data) {
			var data_key = data.subdomain + '/' + data.path + '/' + data.key;

			// remove gaiji
			data.html = data.html.replace(/[\uE020-\uF8FF]/g, '');

			eorzeadb.popup_contents[data_key] = data.html;
		},
		init_after_domready: function() {
			eorzeadb.init_tooltip_frame();
			eorzeadb.init_db_links();
		},
		is_tablet_device: function() {
			var ua = navigator.userAgent;
			var isTouch = ('ontouchstart' in window) || navigator.maxTouchPoints > 0 || navigator.msMaxTouchPoints > 1;
			return isTouch && (
				ua.indexOf('iPad') !== -1 ||
				(ua.indexOf('Macintosh') !== -1 && 'ontouchend' in document) ||
				(ua.indexOf('Android') !== -1 && ua.indexOf('Mobile') === -1)
			);
		},
		is_tablet_text_link: function(db_link) {
			return eorzeadb.is_tablet_device() && db_link.tagName.toLowerCase() === 'a';
		},
		init_tooltip_frame: function() {
			var tooltip = document.getElementById('eorzeadb_tooltip');
			if ( !tooltip ) {
				tooltip = document.createElement('div');
				tooltip.id = 'eorzeadb_tooltip';
				tooltip.style.display = 'none';
				tooltip.style.position = 'absolute';
				tooltip.style.top  = '0';
				tooltip.style.left = '0';
				document.body.appendChild(tooltip);

				tooltip.addEventListener('mouseenter', function() {
					eorzeadb._cancel_hide();
					tooltip.style.transition = '';
					tooltip.style.opacity = '1';
					tooltip.style.display = '';
					eorzeadb.is_tooltip_show = true;
					var inner = tooltip.querySelectorAll('.js__tooltip');
					for ( var i = 0; i < inner.length; i++ ) {
						eorzeadb._setup_inner_tooltip(inner[i]);
					}
				});
				tooltip.addEventListener('mouseleave', function() {
					eorzeadb.hide_tooltip();
				});
				tooltip.addEventListener('click', function() {
					if ( eorzeadb.is_tooltip_show ) {
						eorzeadb.hide_tooltip();
					}
					else {
						eorzeadb.is_tooltip_show = true;
					}
				});
			}
			eorzeadb.$tooltip = tooltip;
		},
		init_db_links: function() {
			var hover_timer = null;
			document.body.addEventListener('mouseover', function(e) {
				var link = e.target.closest && e.target.closest('.eorzeadb_link');
				if ( !link ) return;
				if ( eorzeadb.is_tablet_text_link(link) ) return;
				if ( e.relatedTarget && link.contains(e.relatedTarget) ) return;
				if ( hover_timer ) {
					clearTimeout(hover_timer);
					hover_timer = null;
				}
				hover_timer = setTimeout(function() {
					eorzeadb.show_tooltip(link);
				}, 300);
			});
			document.body.addEventListener('mouseout', function(e) {
				var link = e.target.closest && e.target.closest('.eorzeadb_link');
				if ( !link ) return;
				if ( eorzeadb.is_tablet_text_link(link) ) return;
				if ( e.relatedTarget && link.contains(e.relatedTarget) ) return;
				if ( hover_timer ) {
					clearTimeout(hover_timer);
					hover_timer = null;
				}
				eorzeadb.hide_tooltip();
			});
		},
		show_tooltip: function(db_link) {
			eorzeadb.get_popup_content(db_link, function(this_popup_content) {
				if ( !this_popup_content ) {
					return;
				}

				var $tt = eorzeadb.$tooltip;
				eorzeadb._cancel_hide();
				$tt.style.transition = '';
				$tt.style.opacity = '1';
				$tt.innerHTML = this_popup_content;
				$tt.style.display = '';
				eorzeadb.set_tooltip_position(db_link);
				eorzeadb.is_tooltip_show = true;
				eorzeadb.init_tooltip_html();
			});
		},
		_cancel_hide: function() {
			if ( eorzeadb._hide_timer ) {
				clearTimeout(eorzeadb._hide_timer);
				eorzeadb._hide_timer = null;
			}
		},
		hide_tooltip: function() {
			var $tt = eorzeadb.$tooltip;
			if ( !$tt ) return;
			eorzeadb.is_tooltip_show = false;
			eorzeadb._cancel_hide();
			$tt.style.transition = 'opacity 500ms';
			$tt.style.opacity = '0';
			eorzeadb._hide_timer = setTimeout(function() {
				$tt.style.display = 'none';
				$tt.style.transition = '';
				eorzeadb._hide_timer = null;
			}, 500);
		},
		init_tooltip_html: function() {
			var $tt = eorzeadb.$tooltip;
			var anchors = $tt.querySelectorAll('a');
			for ( var i = 0; i < anchors.length; i++ ) {
				anchors[i].target = '_blank';
			}
			var year = String(new Date().getFullYear());
			var year_els = $tt.querySelectorAll('.eorzeadb_tooltip_this_year');
			for ( var y = 0; y < year_els.length; y++ ) {
				year_els[y].textContent = year;
			}

			var setBg = function(nodes, color) {
				for ( var n = 0; n < nodes.length; n++ ) {
					nodes[n].style.backgroundColor = color;
				}
			};
			var columns = $tt.querySelectorAll('.tooltip_view .table_black .column1');
			for ( var c = 0; c < columns.length; c++ ) {
				var col = columns[c];
				setBg(col.querySelectorAll('td .no_th tr:nth-child(odd) td'), '#2e2e2e');
				setBg(col.querySelectorAll('td .no_th tr:nth-child(even) td'), '#333333');
				setBg(col.querySelectorAll('tr:nth-child(even) td'), '#2e2e2e');
				setBg(col.querySelectorAll('tr:nth-child(odd) td'), '#333333');
				setBg(col.querySelectorAll('.inr_table tr:nth-child(even) td'), '#2e2e2e');
				setBg(col.querySelectorAll('.inr_table tr:nth-child(odd) td'), '#333333');
			}
		},
		get_url_info: function(db_link) {
			var ldst_href = db_link.getAttribute('data-ldst-href') || db_link.getAttribute('href');
			var matchs = ldst_href.match(/^(https?:\/\/([^\.]+)\..*playguide\/db\/([^#\?]*?))\/?(\?.+)?(#.+)?$/);
			var subdomain = matchs[2];
			var path      = matchs[3];
			subdomain = subdomain.replace('cloud','');
			var url;
			if ( !eorzeadb.dynamic_tooltip && eorzeadb.versions.data ) {
				url = eorzeadb.cdn_prefix + 'pc/tooltip/'+ eorzeadb.versions.data + '/' + subdomain + '/' + path + '.js';
			}
			else {
				url = matchs[1] + '/jsonp/';
				url = url.replace(/^http:/, 'https:');
			}
			return {
				'url': url,
				'data_key': subdomain + '/' + path
			};
		},
		get_popup_content: function(db_link, cb) {
			var url_info = eorzeadb.get_url_info(db_link);
			eorzeadb.popup_content_last_key = url_info.data_key;
			if ( eorzeadb.popup_contents.hasOwnProperty(url_info.data_key) ) {
				if ( cb ) { cb(eorzeadb.popup_contents[url_info.data_key]); }
				return;
			}
			eorzeadb.popup_contents[url_info.data_key] = '';

			var script = document.createElement('script');
			script.async = true;
			var done = function() {
				if ( cb && eorzeadb.popup_content_last_key === url_info.data_key ) {
					cb(eorzeadb.popup_contents[url_info.data_key]);
				}
				if ( script.parentNode ) {
					script.parentNode.removeChild(script);
				}
			};
			script.onload  = done;
			script.onerror = function() {
				if ( script.parentNode ) {
					script.parentNode.removeChild(script);
				}
			};
			script.src = url_info.url;
			(document.head || document.documentElement).appendChild(script);
		},
		set_tooltip_position: function(db_link) {
			var $tooltip       = eorzeadb.$tooltip;
			var $tooltip_child = $tooltip.firstElementChild;
			if ( !$tooltip_child ) return;

			var tooltip_height    = $tooltip_child.offsetHeight + 26;
			var tooltip_width     = $tooltip_child.offsetWidth;
			var window_scroll_top = window.pageYOffset || document.documentElement.scrollTop || 0;
			var window_scroll_lft = window.pageXOffset || document.documentElement.scrollLeft || 0;
			var link_rect         = db_link.getBoundingClientRect();
			var link_offset_top   = Math.round(link_rect.top + window_scroll_top);
			var link_offset_left  = link_rect.left + window_scroll_lft;
			var link_width        = db_link.offsetWidth;
			var window_width      = window.innerWidth;
			var window_height     = window.innerHeight;
			var tooltip_under_pos = link_offset_top - window_scroll_top + tooltip_height;

			var top_pos, left_pos;

			if ( (window_width - link_offset_left - link_width - 10) > tooltip_width ) {
				left_pos = link_width + link_offset_left + 10;
			}
			else {
				left_pos = link_offset_left - 10 - tooltip_width - 20;
				if ( left_pos < 0 ) {
					left_pos = link_width + link_offset_left + 10;
				}
			}

			if ( tooltip_under_pos > window_height ) {
				if ( window_height < tooltip_height ) {
					top_pos = window_scroll_top;
				}
				else {
					top_pos = link_offset_top - (tooltip_under_pos - window_height);
				}
			}
			else if ( link_offset_top > window_scroll_top && window_height > tooltip_height ) {
				top_pos = link_offset_top;
			}
			else {
				top_pos = window_scroll_top - link_offset_top;
			}

			$tooltip.style.top  = top_pos  + 'px';
			$tooltip.style.left = left_pos + 'px';
		},
		_setup_inner_tooltip: function(el) {
			if ( el.__eorzeadb_tooltip_bound ) return;
			el.__eorzeadb_tooltip_bound = true;

			var ua = navigator.userAgent;
			if ( /iPhone|iPad|iPod/.test(ua) ) return;

			var content = document.querySelector('.eorzeadb_tooltip__text');
			if ( !content ) {
				content = document.createElement('div');
				content.className = 'eorzeadb_tooltip__text';
				document.body.appendChild(content);
			}
			content.style.position = 'fixed';
			content.style.display = 'none';

			el.style.cursor = 'normal';

			var _title;
			// share fade timer on the content element so a stale fadeOut from one
			// .js__tooltip cannot hide content shown by a different .js__tooltip
			var cancelFade = function() {
				if ( content._fade_timer ) {
					clearTimeout(content._fade_timer);
					content._fade_timer = null;
				}
			};
			var fadeOut = function() {
				cancelFade();
				content.style.transition = 'opacity 500ms';
				content.style.opacity = '0';
				content._fade_timer = setTimeout(function() {
					content.style.display = 'none';
					content.style.transition = '';
					content._fade_timer = null;
				}, 500);
			};

			el.addEventListener('mouseenter', function() {
				_title = el.getAttribute('data-tooltip');
				cancelFade();
				content.style.transition = '';
				content.style.display = 'block';
				content.style.opacity = '1';
				content.innerHTML = _title;
				var inner_a = el.querySelector('a');
				if ( inner_a ) {
					inner_a.setAttribute('data-tooltip', '');
				}
			});
			el.addEventListener('mouseleave', function() {
				var inner_a = el.querySelector('a');
				if ( inner_a ) {
					inner_a.setAttribute('data-tooltip', _title);
				}
				fadeOut();
			});
			el.addEventListener('mousemove', function(e) {
				var posTop  = e.clientY + 20;
				var posLeft = e.clientX;
				var content_w = content.offsetWidth;
				if ( posLeft + content_w > window.innerWidth ) {
					posTop  = e.clientY + content.offsetHeight;
					posLeft = posLeft - ((posLeft + content_w - window.innerWidth) + 10);
				}
				content.style.top  = posTop  + 'px';
				content.style.left = posLeft + 'px';
			});
			el.addEventListener('mousedown', function() {
				fadeOut();
			});
		}
	};
	eorzeadb.init = function() {
		// preserve config that the host page set on `eorzeadb` (cdn_prefix, version_js_uri,
		// dynamic_tooltip, versions, etc.) by merging it on top of klass defaults.
		for ( var k in eorzeadb ) {
			if ( eorzeadb.hasOwnProperty(k) ) {
				eorzeadb_klass[k] = eorzeadb[k];
			}
		}
		window.eorzeadb = eorzeadb = eorzeadb_klass;

		if ( document.readyState === 'loading' ) {
			document.addEventListener('DOMContentLoaded', eorzeadb.init_after_domready);
		}
		else {
			eorzeadb.init_after_domready();
		}
	};
})();
