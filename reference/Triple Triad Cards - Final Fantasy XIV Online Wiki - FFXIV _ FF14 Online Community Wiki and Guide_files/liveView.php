			// <script type="text/javascript">
			(function () {
				var SekindoClientDetections_GDPR = function (isDebug, globalTimeout, onConsentAvail, isApp) {

	this.CONSENT_SDK_NOT_AVAILABLE = -100;
	this.CONSENT_STILL_RUNNING = -2;
	this.CONSENT_REJECTED = 0;
	this.CONSENT_APPROVED = 1;
	this.CONSENT_NOT_APPLY = 2;
	this.CONSENT_ANOTHER_VER = 3;

	this.PRIVACY_DETECTION_TIMEOUT_STEP_MS = 50;


	this.VENDOR_ID = 228;
	this.PURPOSES = [1,3,4,5];

	this.isCmpLoaded = false;
	this.consentState = this.CONSENT_STILL_RUNNING;
	this.consentRawData = null;
	this.debug = isDebug;
	this.requestTimeout = globalTimeout;
	this.isApp = isApp;

	this.startTs = new Date().getTime();

	if (onConsentAvail && typeof onConsentAvail == 'function')
		this.onConsentAvail = onConsentAvail;
	else
		this.onConsentAvail = null;

	this.cmpCallsList = {};

	if (typeof window.Sekindo == 'undefined')
		window.Sekindo = {};
	if (typeof window.Sekindo.clientConsentEncoded == 'undefined')
		window.Sekindo.clientConsentEncoded = null;

	this.getState = function()
	{
		return this.consentState;
	};

	this.getConsent = function()
	{
		return this.consentRawData ? this.consentRawData : '';
	};

	this._postMessage = function (cb, command)
	{
		try
		{
			var tempTs = new Date().getTime();
			var callId = "PrimisCmpCall_"+command+"_"+Math.random().toString()+"_"+tempTs.toString();
			this.cmpCallsList[callId] = {
				'cmd': command,
				'cb': cb
			};
			var message = {
				__cmpCall: {
					callId: callId,
					command: command
				}
			};
			if (this.debug)
				console.log("SEKDBG/GDPR: Sending message '"+command+"' to CMP");
			window.addEventListener('message', this.cmpCallsList[callId].cb);
			window.top.postMessage(message, '*');
			return true;
		}
		catch (e)
		{
			if (this.debug)
			{
				console.log("SEKDBG/GDPR: Failed to send message '"+command+"' to CMP");
				console.log(e);
			}
			return false;
		};
	};

	this._clearMessages = function (filterCallId)
	{
		for (var callId in this.cmpCallsList)
		{
			if (filterCallId && callId != filterCallId)
				continue;
			if (!this.cmpCallsList.hasOwnProperty(callId))
				continue;
			if (typeof this.cmpCallsList[callId].cb === 'function')
				window.removeEventListener('message', this.cmpCallsList[callId].cb);
			delete this.cmpCallsList[callId];
		}
	};

	this._call = function (command)
	{
		var ref = this;

		if (this.consentState != this.CONSENT_STILL_RUNNING || !this.cmpCallbacksList.hasOwnProperty(command) ||
			typeof this.cmpCallbacksList[command] !== 'function')
		{
			this._clearMessages();
			return;
		}

		var currTs = new Date().getTime();
		if (currTs - ref.startTs >= this.requestTimeout) /* Timeout reached */
		{
			this._clearMessages();
			return;
		}

		if (this.cmpStopCallbacksList.hasOwnProperty(command) && typeof this.cmpStopCallbacksList[command] === 'function' && this.cmpStopCallbacksList[command]())
		{
			if (this.debug)
				console.log("SEKDBG/GDPR: Stopping "+command+" due to reached goals");
			return;
		}

		try
		{
			window.top.__cmp(command, null, this.cmpCallbacksList[command]);
			if (ref.debug)
				console.log("SEKDBG/GDPR: Using DIRECT/"+command);
		}
		catch (e)
		{
			/* Trap to check if another version is supported */
			try
			{
				var otherVer = window.top.__tcfapi;
				if (typeof window.top.__tcfapi !== 'undefined')
				{
					this.consentState = this.CONSENT_ANOTHER_VER;
					if (ref.debug)
						console.log("SEKDBG/GDPR: Skipping due to another version");
					return;
				}
			}
			catch (eGdprNewer)
			{

			}

			try
			{
				var safeFrameHandler = window.extern || window.$sf.ext;
				safeFrameHandler.ext.register(300, 250, function (msgCat, msg) {
					if (msgCat !== 'cmpReturn')
						return;

					if (ref.cmpCallbacksList.hasOwnProperty(msg.cmpCommand) && typeof ref.cmpCallbacksList[msg.cmpCommand] === 'function')
						ref.cmpCallbacksList[msg.cmpCommand](msg.VendorConsents);
				});

				safeFrameHandler.ext.cmp(command);
				if (this.debug)
					console.log("SEKDBG/GDPR: Using SAFE_FRAME/"+command);
			}
			catch (eSf)
			{
				if (this.debug)
					console.log("SEKDBG/GDPR: Using MESSAGING/"+command);
				this._postMessage(function (evt) {
					if (evt && evt.data && evt.data.__cmpReturn && evt.data.__cmpReturn.returnValue && evt.data.__cmpReturn.callId)
					{
						if (ref.debug)
							console.log("SEKDBG/GDPR: Received message '"+evt.data.__cmpReturn.callId+"' from channel");
						if (ref.cmpCallsList.hasOwnProperty(evt.data.__cmpReturn.callId))
						{
							if (typeof ref.cmpCallsList[evt.data.__cmpReturn.callId].cmd === 'string')
							{
								var cmd = ref.cmpCallsList[evt.data.__cmpReturn.callId].cmd;
								if (ref.cmpCallbacksList.hasOwnProperty(cmd) && typeof ref.cmpCallbacksList[cmd] === 'function')
									ref.cmpCallbacksList[cmd](evt.data.__cmpReturn.returnValue);
							}
							ref._clearMessages(evt.data.__cmpReturn.callId);
						}
					}
					else if (ref.debug && evt && evt.data && evt.data.__cmpReturn)
					{
						console.log("SEKDBG/GDPR: Received corrupted message from channel");
						console.log(evt);
					}
				}, command);
			}
		}

		if (this.consentState == this.CONSENT_STILL_RUNNING && currTs - this.startTs < this.requestTimeout)
		{
			if (!this.cmpStopCallbacksList.hasOwnProperty(command) || typeof this.cmpStopCallbacksList[command] !== 'function' ||
				!this.cmpStopCallbacksList[command]())
			{
				setTimeout(function () {
					ref._call(command);
				}, this.PRIVACY_DETECTION_TIMEOUT_STEP_MS);
			}
			else
			{
				this._clearMessages();
			}
		}
		else
		{
			this._clearMessages();
		}
	};

	this._verify = function (rawConsent)
	{
		if (this.consentState != this.CONSENT_STILL_RUNNING) /* Already finished before ... */
			return;

		if (typeof rawConsent.gdprApplies !== 'undefined' && !rawConsent.gdprApplies)
		{
			if (this.debug)
				console.log("SEKDBG/GDPR: Consent SDK checked that GDPR does not apply for this client");
			this.consentState = this.CONSENT_NOT_APPLY;
			return true;
		}

		if (typeof rawConsent.consentData !== 'string')
		{
			if (this.debug)
			{
				console.log("SEKDBG/GDPR: Bad consent data is provided");
				console.log(rawConsent.consentData);
				console.log(rawConsent);
			}
			this.consentState = this.CONSENT_SDK_NOT_AVAILABLE;
			return false;
		}

		if (!SekindoConsentHandler || !SekindoConsentHandler.ConsentString)
		{
			if (this.debug)
				console.log("SEKDBG/GDPR: IAB Consent SDK is not available");
			this.consentState = this.CONSENT_SDK_NOT_AVAILABLE;
			return false;
		}

		if (this.debug)
		{
			console.log("SEKDBG/GDPR: Consent returned by SDK:");
			console.log(rawConsent);
		}

		var consentHandler = new SekindoConsentHandler.ConsentString(rawConsent.consentData);
		var acceptedVendors = consentHandler.getVendorsAllowed();
		if (!acceptedVendors || acceptedVendors.indexOf(this.VENDOR_ID) == -1)
		{
			if (this.debug)
				console.log("SEKDBG/GDPR: Vendor rejected by client");
			this.consentState = this.CONSENT_REJECTED;
			this.consentRawData = rawConsent.consentData;
			return false;
		}

		for (i = 0, len = this.PURPOSES.length; i < len; i ++)
		{
			if (!consentHandler.isPurposeAllowed(this.PURPOSES[i]))
			{
				if (this.debug)
					console.log("SEKDBG/GDPR: Purpose "+this.PURPOSES[i]+" rejected by client");
				this.consentState = this.CONSENT_REJECTED;
				this.consentRawData = rawConsent.consentData;
				return false;
			}
		}

		this.consentState = this.CONSENT_APPROVED;
		this.consentRawData = rawConsent.consentData;

		if (this.debug)
			console.log("SEKDBG/GDPR: Vendor approval received");

		return true;
	};

	var ref = this;

	this.cmpCallbacksList = {
		ping: function (result) {
				if (typeof result.cmpLoaded !== 'undefined' && result.cmpLoaded)
				{
					ref.isCmpLoaded = true;
					if (ref.debug)
						console.log("SEKDBG/GDPR: CMP library is now fully loaded");
					if (typeof ref.onCmpLoaded === 'function')
						ref.onCmpLoaded();
				}
		},
		getConsentData: function (result) {
				ref._verify(result);

				/* On success/non-required, call the availability callback */
				if (ref.onConsentAvail && (ref.consentState == ref.CONSENT_APPROVED || ref.consentState == ref.CONSENT_REJECTED))
					ref.onConsentAvail(ref.consentRawData, ref.consentState == ref.CONSENT_APPROVED);
		}
	};

	this.cmpStopCallbacksList = {
		ping: function () {
			return ref.isCmpLoaded;
		}
	};

	this.onCmpLoaded = function () {
		this._call('getConsentData');
	};

	/* Track CMP state and fetch data then ready */
	if (!this.isApp) {
		this._call('ping');
	}
};
/* CMP v2 Implementation - TCF 2.2 */
var SekindoClientDetections_GDPR_v2 = function (isDebug, globalTimeout, onConsentAvail, isApp) {
	this.CONSENT_SDK_NOT_AVAILABLE = -100;
	this.CONSENT_STILL_RUNNING = -2;
	this.CONSENT_REJECTED = 0;
	this.CONSENT_APPROVED = 1;
	this.CONSENT_NOT_APPLY = 2;
	this.CONSENT_ANOTHER_VER = 3;

	this.VERSION = 2;

	this.PRIVACY_DETECTION_TIMEOUT_STEP_MS = 50;

	this.VENDOR_ID = 228;
	this.PURPOSES = [1,2,5,6,7,8];

	this.isCmpLoaded = false;
	this.cmpVersion = '';
	this.consentState = this.CONSENT_STILL_RUNNING;
	this.consentRawData = null;
	this.debug = isDebug;
	this.requestTimeout = globalTimeout;
	this.isApp = isApp;

	this.startTs = new Date().getTime();

	if (onConsentAvail && typeof onConsentAvail == 'function')
		this.onConsentAvail = onConsentAvail;
	else
		this.onConsentAvail = null;

	this.tcfCallsList = {};

	if (typeof window.Sekindo == 'undefined')
		window.Sekindo = {};
	if (typeof window.Sekindo.clientConsentEncoded == 'undefined')
		window.Sekindo.clientConsentEncoded = null;

	this.getState = function()
	{
		return this.consentState;
	};

	this.getConsent = function()
	{
		return this.consentRawData ? this.consentRawData : '';
	};

	this._postMessage = function (cb, command, param)
	{
		try
		{
			var tempTs = new Date().getTime();
			var callId = "PrimisCmp2Call_"+command+"_"+Math.random().toString()+"_"+tempTs.toString();
			this.tcfCallsList[callId] = {
				'cmd': command,
				'cb': cb
			};
			var message = {
				__tcfapiCall: {
					callId: callId,
					command: command,
					parameter: param,
					version: this.VERSION
				}
			};
			if (this.debug)
				console.log("SEKDBG/GDPRv2: Sending message '"+command+"' to CMP");
			window.addEventListener('message', this.tcfCallsList[callId].cb);
			window.top.postMessage(message, '*');
			return true;
		}
		catch (e)
		{
			if (this.debug)
			{
				console.log("SEKDBG/GDPRv2: Failed to send message '"+command+"' to CMP");
				console.log(e);
			}
			return false;
		};
	};

	this._clearMessages = function (filterCallId)
	{
		for (var callId in this.tcfCallsList)
		{
			if (filterCallId && callId != filterCallId)
				continue;
			if (!this.tcfCallsList.hasOwnProperty(callId))
				continue;
			if (typeof this.tcfCallsList[callId].cb === 'function')
				window.removeEventListener('message', this.tcfCallsList[callId].cb);
			delete this.tcfCallsList[callId];
		}
	};

	this._call = function (command, param)
	{
		var ref = this;
		const isEventListenerCmd = (command == 'addEventListener' || command == 'removeEventListener');
		if ((this.consentState != this.CONSENT_STILL_RUNNING || !this.tcfCallbacksList.hasOwnProperty(command) ||
			typeof this.tcfCallbacksList[command] !== 'function') && !isEventListenerCmd)
		{
			this._clearMessages();
			return;
		}

		var currTs = new Date().getTime();
		if (currTs - ref.startTs >= this.requestTimeout && !isEventListenerCmd) /* Timeout reached */
		{
			this._clearMessages();
			return;
		}

		if (this.tcfStopCallbacksList.hasOwnProperty(command) && typeof this.tcfStopCallbacksList[command] === 'function'
			&& this.tcfStopCallbacksList[command]() && !isEventListenerCmd)
		{
			if (this.debug)
				console.log("SEKDBG/GDPRv2: Stopping "+command+" due to reached goals");
			return;
		}

		try
		{
			window.top.__tcfapi(command, this.VERSION, this.tcfCallbacksList[command], param);
			if (ref.debug)
				console.log("SEKDBG/GDPRv2: Using DIRECT/"+command);
		}
		catch (e)
		{
			if (ref.debug)
			{
				console.log("SEKDBG/GDPRv2: Exception during DIRECT check");
				console.log(e);
			}
			/* Trap to check if another version is supported */
			try
			{
				var otherVer = window.top.__cmp;
				if (typeof window.top.__cmp !== 'undefined')
				{
					this.consentState = this.CONSENT_ANOTHER_VER;
					if (ref.debug)
						console.log("SEKDBG/GDPRv2: Skipping due to another version");
					return;
				}
			}
			catch (eGdprOlder)
			{

			}

			try
			{
				var safeFrameHandler = window.extern || window.$sf.ext;
				safeFrameHandler.ext.register(300, 250, function (msgCat, msg) {
					if (msgCat !== 'tcfapiReturn')
						return;

					if (ref.tcfCallbacksList.hasOwnProperty(msg.cmpCommand) && typeof ref.tcfCallbacksList[msg.cmpCommand] === 'function')
						ref.tcfCallbacksList[msg.cmpCommand](msg.VendorConsents);
				});

				safeFrameHandler.ext.tcfapi(command, param);
				if (this.debug)
					console.log("SEKDBG/GDPRv2: Using SAFE_FRAME/"+command);
			}
			catch (eSf)
			{
				if (this.debug)
					console.log("SEKDBG/GDPRv2: Using MESSAGING/"+command);
				this._postMessage(function (evt) {
					if (evt && evt.data && evt.data.__tcfapiReturn && evt.data.__tcfapiReturn.returnValue && evt.data.__tcfapiReturn.callId)
					{
						if (ref.debug)
							console.log("SEKDBG/GDPRv2: Received message '"+evt.data.__tcfapiReturn.callId+"' from channel");
						if (ref.tcfCallsList.hasOwnProperty(evt.data.__tcfapiReturn.callId))
						{
							if (ref.debug)
								console.log("SEKDBG/GDPRv2: Checking own message '"+evt.data.__tcfapiReturn.callId+"' from channel");
							if (typeof ref.tcfCallsList[evt.data.__tcfapiReturn.callId].cmd === 'string')
							{
								var cmd = ref.tcfCallsList[evt.data.__tcfapiReturn.callId].cmd;
								if (ref.tcfCallbacksList.hasOwnProperty(cmd) && typeof ref.tcfCallbacksList[cmd] === 'function')
									ref.tcfCallbacksList[cmd](evt.data.__tcfapiReturn.returnValue);
							}
							ref._clearMessages(evt.data.__tcfapiReturn.callId);
						}
					}
					else if (ref.debug && evt && evt.data && evt.data.__tcfapiReturn)
					{
						console.log("SEKDBG/GDPRv2: Received corrupted message from channel");
						console.log(evt);
					}
				}, command, param);
			}
		}

		if (isEventListenerCmd)
			return;

		if (this.consentState == this.CONSENT_STILL_RUNNING && currTs - this.startTs < this.requestTimeout)
		{
			if (!this.tcfStopCallbacksList.hasOwnProperty(command) || typeof this.tcfStopCallbacksList[command] !== 'function' ||
				!this.tcfStopCallbacksList[command]())
			{
				setTimeout(function () {
					if (ref.debug)
						console.log("SEKDBG/GDPRv2: Reissuing command "+command+" to run again because consent is still not available.");
					ref._call(command);
				}, this.PRIVACY_DETECTION_TIMEOUT_STEP_MS);
			}
			else
			{
				this._clearMessages();
			}
		}
		else
		{
			this._clearMessages();
		}
	};

	this._verify = function (rawConsent, isUpdate)
	{
		if (this.consentState != this.CONSENT_STILL_RUNNING && !isUpdate) /* Already finished before ... */
			return;

		if (typeof rawConsent.gdprApplies !== 'undefined' && !rawConsent.gdprApplies)
		{
			if (this.debug)
				console.log("SEKDBG/GDPRv2: Consent SDK checked that GDPR does not apply for this client");
			this.consentState = this.CONSENT_NOT_APPLY;
			return true;
		}

		if (typeof rawConsent.tcString !== 'string')
		{
			if (this.debug)
			{
				console.log("SEKDBG/GDPRv2: Bad consent data is provided");
				console.log(rawConsent.tcString);
				console.log(rawConsent);
			}
			this.consentState = this.CONSENT_SDK_NOT_AVAILABLE;
			return false;
		}

		if (this.debug)
		{
			console.log("SEKDBG/GDPRv2: Consent returned by SDK:");
			console.log(rawConsent);
		}

		if (rawConsent.vendor.consents[this.VENDOR_ID] === undefined || !rawConsent.vendor.consents[this.VENDOR_ID])
		{
			if (this.debug)
				console.log("SEKDBG/GDPRv2: Vendor rejected by client");
			this.consentState = this.CONSENT_REJECTED;
			this.consentRawData = rawConsent.tcString;
			return false;
		}

		for (i = 0, len = this.PURPOSES.length; i < len; i ++)
		{
			if (rawConsent.purpose.consents[this.PURPOSES[i]] === undefined || !rawConsent.purpose.consents[this.PURPOSES[i]])
			{
				if (this.debug)
					console.log("SEKDBG/GDPRv2: Purpose "+this.PURPOSES[i]+" rejected by client");
				this.consentState = this.CONSENT_REJECTED;
				this.consentRawData = rawConsent.tcString;
				return false;
			}
		}

		this.consentState = this.CONSENT_APPROVED;
		this.consentRawData = rawConsent.tcString;

		if (this.debug)
			console.log("SEKDBG/GDPRv2: Vendor approval received");

		return true;
	};

	var ref = this;

	this.tcfCallbacksList = {
		ping: function (result) {
				if (typeof result.cmpLoaded !== 'undefined' && result.cmpLoaded)
				{
					ref.isCmpLoaded = true;
					if (result.cmpVersion !== undefined)
						ref.cmpVersion = result.cmpVersion;
					if (ref.debug)
						console.log("SEKDBG/GDPRv2: CMP library is now fully loaded");
					if (typeof ref.onCmpLoaded === 'function')
						ref.onCmpLoaded();
				}
		},
		addEventListener: function (result, isSuccess) {
			if (isSuccess && (result.eventStatus == 'useractioncomplete' || result.eventStatus == 'tcloaded')) {
				ref._verify(result, result.eventStatus == 'useractioncomplete');
				/* On success/non-required, call the availability callback */
				if (ref.onConsentAvail && (ref.consentState == ref.CONSENT_APPROVED || ref.consentState == ref.CONSENT_REJECTED)) {
					ref.onConsentAvail(ref.consentRawData, ref.consentState == ref.CONSENT_APPROVED);
					/* Not removing the event listener to allow interception of user consent change action */
				}
			}
		}
	};

	this.tcfStopCallbacksList = {
		ping: function () {
			return ref.isCmpLoaded;
		}
	};

	this.onCmpLoaded = function () {
		/* In TCF 2.2 the getTCData is deprecated, using the addEventListener only */
		this._call('addEventListener');
	};

	/* Track CMP state and fetch data then ready */
	if (!this.isApp) {
		this._call('ping');
	}
};
var SekindoConsentHandler=function(e){var n={};function t(r){if(n[r])return n[r].exports;var o=n[r]={i:r,l:!1,exports:{}};return e[r].call(o.exports,o,o.exports,t),o.l=!0,o.exports}return t.m=e,t.c=n,t.d=function(e,n,r){t.o(e,n)||Object.defineProperty(e,n,{configurable:!1,enumerable:!0,get:r})},t.r=function(e){Object.defineProperty(e,"__esModule",{value:!0})},t.n=function(e){var n=e&&e.__esModule?function(){return e.default}:function(){return e};return t.d(n,"a",n),n},t.o=function(e,n){return Object.prototype.hasOwnProperty.call(e,n)},t.p="/content/ClientDetections/",t(t.s=8)}([function(e,n,t){"use strict";"function"==typeof Symbol&&Symbol.iterator;var r,o=(Array.from||(function(e){return"function"==typeof e},r=Math.pow(2,53)-1,function(e){var n=function(e){var n=Number(e);return isNaN(n)?0:0!==n&&isFinite(n)?(n>0?1:-1)*Math.floor(Math.abs(n)):n}(e);return Math.min(Math.max(n,0),r)},function(e){var n=e.next();return!Boolean(n.done)&&n}),t(2)),i=o.decodeBitsToIds,a=o.decodeFromBase64;e.exports={decodeConsentString:function(e){var n=a(e),t=n.version,r=n.cmpId,o=n.vendorListVersion,s=n.purposeIdBitString,u=n.maxVendorId,d=n.created,c=n.lastUpdated,l=n.isRange,f=n.defaultConsent,p=n.vendorIdBitString,h=n.vendorRangeList,v=n.cmpVersion,m=n.consentScreen,y=n.consentLanguage,g={version:t,cmpId:r,vendorListVersion:o,allowedPurposeIds:i(s),maxVendorId:u,created:d,lastUpdated:c,cmpVersion:v,consentScreen:m,consentLanguage:y};if(l){var b=h.reduce(function(e,n){for(var t=n.isRange,r=n.startVendorId,o=n.endVendorId,i=t?o:r,a=r;a<=i;a+=1)e[a]=!0;return e},{});g.allowedVendorIds=[];for(var w=0;w<=u;w+=1)(f&&!b[w]||!f&&b[w])&&-1===g.allowedVendorIds.indexOf(w)&&g.allowedVendorIds.push(w)}else g.allowedVendorIds=i(p);return g}}},function(e,n,t){"use strict";var r;"function"==typeof Symbol&&Symbol.iterator;Array.from||(function(e){return"function"==typeof e},r=Math.pow(2,53)-1,function(e){var n=function(e){var n=Number(e);return isNaN(n)?0:0!==n&&isFinite(n)?(n>0?1:-1)*Math.floor(Math.abs(n)):n}(e);return Math.min(Math.max(n,0),r)}),e.exports={versionNumBits:6,vendorVersionMap:{1:{version:1,metadataFields:["version","created","lastUpdated","cmpId","cmpVersion","consentScreen","vendorListVersion"],fields:[{name:"version",type:"int",numBits:6},{name:"created",type:"date",numBits:36},{name:"lastUpdated",type:"date",numBits:36},{name:"cmpId",type:"int",numBits:12},{name:"cmpVersion",type:"int",numBits:12},{name:"consentScreen",type:"int",numBits:6},{name:"consentLanguage",type:"language",numBits:12},{name:"vendorListVersion",type:"int",numBits:12},{name:"purposeIdBitString",type:"bits",numBits:24},{name:"maxVendorId",type:"int",numBits:16},{name:"isRange",type:"bool",numBits:1},{name:"vendorIdBitString",type:"bits",numBits:function(e){return e.maxVendorId},validator:function(e){return!e.isRange}},{name:"defaultConsent",type:"bool",numBits:1,validator:function(e){return e.isRange}},{name:"numEntries",numBits:12,type:"int",validator:function(e){return e.isRange}},{name:"vendorRangeList",type:"list",listCount:function(e){return e.numEntries},validator:function(e){return e.isRange},fields:[{name:"isRange",type:"bool",numBits:1},{name:"startVendorId",type:"int",numBits:16},{name:"endVendorId",type:"int",numBits:16,validator:function(e){return e.isRange}}]}]}}}},function(e,n,t){"use strict";var r,o,i,a,s="function"==typeof Symbol&&"symbol"==typeof Symbol.iterator?function(e){return typeof e}:function(e){return e&&"function"==typeof Symbol&&e.constructor===Symbol&&e!==Symbol.prototype?"symbol":typeof e},u=Array.from||(r=function(e){return"function"==typeof e},o=Math.pow(2,53)-1,i=function(e){var n=function(e){var n=Number(e);return isNaN(n)?0:0!==n&&isFinite(n)?(n>0?1:-1)*Math.floor(Math.abs(n)):n}(e);return Math.min(Math.max(n,0),o)},a=function(e){var n=e.next();return!Boolean(n.done)&&n},function(e){var n,t,o,u=this,d=arguments.length>1?arguments[1]:void 0;if(void 0!==d){if(!r(d))throw new TypeError("Array.from: when provided, the second argument must be a function");arguments.length>2&&(n=arguments[2])}var c=function(e,n){if(null!=e&&null!=n){var t=e[n];if(null==t)return;if(!r(t))throw new TypeError(t+" is not a function");return t}}(e,function(e){if(null!=e){if(["string","number","boolean","symbol"].indexOf(void 0===e?"undefined":s(e))>-1)return Symbol.iterator;if("undefined"!=typeof Symbol&&"iterator"in Symbol&&Symbol.iterator in e)return Symbol.iterator;if("@@iterator"in e)return"@@iterator"}}(e));if(void 0!==c){t=r(u)?Object(new u):[];var l,f,p=c.call(e);if(null==p)throw new TypeError("Array.from requires an array-like or iterable object");for(o=0;;){if(!(l=a(p)))return t.length=o,t;f=l.value,t[o]=d?d.call(n,f,o):f,o++}}else{var h=Object(e);if(null==e)throw new TypeError("Array.from requires an array-like object - not null or undefined");var v,m=i(h.length);for(t=r(u)?Object(new u(m)):new Array(m),o=0;o<m;)v=h[o],t[o]=d?d.call(n,v,o):v,o++;t.length=m}return t}),d=t(6),c=t(1),l=c.versionNumBits,f=c.vendorVersionMap;function p(e){for(var n=arguments.length>1&&void 0!==arguments[1]?arguments[1]:"0",t="",r=0;r<e;r+=1)t+=n;return t}function h(e,n){return p(Math.max(0,n))+e}function v(e,n){return e+p(Math.max(0,n))}function m(e,n){var t="";return"number"!=typeof e||isNaN(e)||(t=parseInt(e,10).toString(2)),n>=t.length&&(t=h(t,n-t.length)),t.length>n&&(t=t.substring(0,n)),t}function y(e){return m(!0===e?1:0,1)}function g(e,n){return e instanceof Date?m(e.getTime()/100,n):m(e,n)}function b(e,n){return m(e.toUpperCase().charCodeAt(0)-65,n)}function w(e){var n=arguments.length>1&&void 0!==arguments[1]?arguments[1]:12;return b(e.slice(0,1),n/2)+b(e.slice(1),n/2)}function S(e,n,t){return parseInt(e.substr(n,t),2)}function V(e,n,t){return new Date(100*S(e,n,t))}function I(e,n){return 1===parseInt(e.substr(n,1),2)}function C(e){var n=S(e);return String.fromCharCode(n+65).toLowerCase()}function A(e,n,t){var r=e.substr(n,t);return C(r.slice(0,t/2))+C(r.slice(t/2))}function B(e){var n=e.input,t=e.field,r=t.name,o=t.type,i=t.numBits,a=t.encoder,s=t.validator;if("function"==typeof s&&!s(n))return"";if("function"==typeof a)return a(n);var u="function"==typeof i?i(n):i,d=n[r],c=null===d||void 0===d?"":d;switch(o){case"int":return m(c,u);case"bool":return y(c);case"date":return g(c,u);case"bits":return v(c,u-c.length).substring(0,u);case"list":return c.reduce(function(e,n){return e+x({input:n,fields:t.fields})},"");case"language":return w(c,u);default:throw new Error("ConsentString - Unknown field type "+o+" for encoding")}}function x(e){var n=e.input;return e.fields.reduce(function(e,t){return e+B({input:n,field:t})},"")}function L(e){var n=e.input,t=e.output,r=e.startPosition,o=e.field,i=o.type,a=o.numBits,s=o.decoder,d=o.validator,c=o.listCount;if("function"==typeof d&&!d(t))return{newPosition:r};if("function"==typeof s)return s(n,t,r);var l="function"==typeof a?a(t):a,f=0;switch("function"==typeof c?f=c(t):"number"==typeof c&&(f=c),i){case"int":return{fieldValue:S(n,r,l)};case"bool":return{fieldValue:I(n,r)};case"date":return{fieldValue:V(n,r,l)};case"bits":return{fieldValue:n.substr(r,l)};case"list":return new Array(f).fill().reduce(function(e){var t=M({input:n,fields:o.fields,startPosition:e.newPosition}),r=t.decodedObject,i=t.newPosition;return{fieldValue:[].concat(function(e){if(Array.isArray(e)){for(var n=0,t=Array(e.length);n<e.length;n++)t[n]=e[n];return t}return u(e)}(e.fieldValue),[r]),newPosition:i}},{fieldValue:[],newPosition:r});case"language":return{fieldValue:A(n,r,l)};default:throw new Error("ConsentString - Unknown field type "+i+" for decoding")}}function M(e){var n=e.input,t=e.fields,r=e.startPosition,o=void 0===r?0:r;return{decodedObject:t.reduce(function(e,t){var r=t.name,i=t.numBits,a=L({input:n,output:e,startPosition:o,field:t}),s=a.fieldValue,u=a.newPosition;return void 0!==s&&(e[r]=s),void 0!==u?o=u:"number"==typeof i&&(o+=i),e},{}),newPosition:o}}function P(e,n){var t=e.version;if("number"!=typeof t)throw new Error("ConsentString - No version field to encode");if(n[t])return x({input:e,fields:n[t].fields});throw new Error("ConsentString - No definition for version "+t)}e.exports={padRight:v,padLeft:h,encodeField:B,encodeDataToBits:P,encodeIntToBits:m,encodeBoolToBits:y,encodeDateToBits:g,encodeLanguageToBits:w,encodeLetterToBits:b,encodeToBase64:function(e){var n=P(e,arguments.length>1&&void 0!==arguments[1]?arguments[1]:f);if(n){for(var t=v(n,7-(n.length+7)%8),r="",o=0;o<t.length;o+=8)r+=String.fromCharCode(parseInt(t.substr(o,8),2));return d.encode(r).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"")}return null},decodeBitsToIds:function(e){return e.split("").reduce(function(e,n,t){return"1"===n&&-1===e.indexOf(t+1)&&e.push(t+1),e},[])},decodeBitsToInt:S,decodeBitsToDate:V,decodeBitsToBool:I,decodeBitsToLanguage:A,decodeBitsToLetter:C,decodeFromBase64:function(e,n){for(var t=e;t.length%4!=0;)t+="=";t=t.replace(/-/g,"+").replace(/_/g,"/");for(var r=d.decode(t),o="",i=0;i<r.length;i+=1){var a=r.charCodeAt(i).toString(2);o+=h(a,8-a.length)}return function(e){var n=arguments.length>1&&void 0!==arguments[1]?arguments[1]:f,t=S(e,0,l);if("number"!=typeof t)throw new Error("ConsentString - Unknown version number in the string to decode");if(!f[t])throw new Error("ConsentString - Unsupported version "+t+" in the string to decode");return M({input:e,fields:n[t].fields}).decodedObject}(o,n)}}},function(e,n,t){"use strict";var r,o,i,a,s="function"==typeof Symbol&&"symbol"==typeof Symbol.iterator?function(e){return typeof e}:function(e){return e&&"function"==typeof Symbol&&e.constructor===Symbol&&e!==Symbol.prototype?"symbol":typeof e},u=Object.assign||function(e){for(var n=1;n<arguments.length;n++){var t=arguments[n];for(var r in t)Object.prototype.hasOwnProperty.call(t,r)&&(e[r]=t[r])}return e},d=Array.from||(r=function(e){return"function"==typeof e},o=Math.pow(2,53)-1,i=function(e){var n=function(e){var n=Number(e);return isNaN(n)?0:0!==n&&isFinite(n)?(n>0?1:-1)*Math.floor(Math.abs(n)):n}(e);return Math.min(Math.max(n,0),o)},a=function(e){var n=e.next();return!Boolean(n.done)&&n},function(e){var n,t,o,u=this,d=arguments.length>1?arguments[1]:void 0;if(void 0!==d){if(!r(d))throw new TypeError("Array.from: when provided, the second argument must be a function");arguments.length>2&&(n=arguments[2])}var c=function(e,n){if(null!=e&&null!=n){var t=e[n];if(null==t)return;if(!r(t))throw new TypeError(t+" is not a function");return t}}(e,function(e){if(null!=e){if(["string","number","boolean","symbol"].indexOf(void 0===e?"undefined":s(e))>-1)return Symbol.iterator;if("undefined"!=typeof Symbol&&"iterator"in Symbol&&Symbol.iterator in e)return Symbol.iterator;if("@@iterator"in e)return"@@iterator"}}(e));if(void 0!==c){t=r(u)?Object(new u):[];var l,f,p=c.call(e);if(null==p)throw new TypeError("Array.from requires an array-like or iterable object");for(o=0;;){if(!(l=a(p)))return t.length=o,t;f=l.value,t[o]=d?d.call(n,f,o):f,o++}}else{var h=Object(e);if(null==e)throw new TypeError("Array.from requires an array-like object - not null or undefined");var v,m=i(h.length);for(t=r(u)?Object(new u(m)):new Array(m),o=0;o<m;)v=h[o],t[o]=d?d.call(n,v,o):v,o++;t.length=m}return t});function c(e){if(Array.isArray(e)){for(var n=0,t=Array(e.length);n<e.length;n++)t[n]=e[n];return t}return d(e)}var l=t(2),f=l.encodeToBase64,p=l.padRight;function h(e){for(var n=arguments.length>1&&void 0!==arguments[1]?arguments[1]:new Set,t=Math.max.apply(Math,[0].concat(c(e.map(function(e){return e.id})),c(d(n)))),r="",o=1;o<=t;o+=1)r+=-1!==n.indexOf(o)?"1":"0";return r}function v(e,n){var t=[],r=e.map(function(e){return e.id});return e.reduce(function(o,i,a){var s=i.id;if(-1!==n.indexOf(s)&&t.push(s),(-1===n.indexOf(s)||a===e.length-1||-1===r.indexOf(s+1))&&t.length){var u=t.shift(),d=t.pop();return t=[],[].concat(c(o),[{isRange:"number"==typeof d,startVendorId:u,endVendorId:d}])}return o},[])}e.exports={convertVendorsToRanges:v,encodeConsentString:function(e){var n=e.maxVendorId,t=e.vendorList,r=void 0===t?{}:t,o=e.allowedPurposeIds,i=e.allowedVendorIds,a=r.vendors,s=void 0===a?[]:a,d=r.purposes,c=void 0===d?[]:d;n||(n=0,s.forEach(function(e){e.id>n&&(n=e.id)}));var l=f(u({},e,{maxVendorId:n,purposeIdBitString:h(c,o),isRange:!1,vendorIdBitString:function(e){for(var n=arguments.length>1&&void 0!==arguments[1]?arguments[1]:[],t="",r=1;r<=e;r+=1)t+=-1!==n.indexOf(r)?"1":"0";return p(t,Math.max(0,e-t.length))}(n,i)})),m=v(s,i),y=f(u({},e,{maxVendorId:n,purposeIdBitString:h(c,o),isRange:!0,defaultConsent:!1,numEntries:m.length,vendorRangeList:m}));return l.length<y.length?l:y}}},function(e,n){var t;t=function(){return this}();try{t=t||Function("return this")()||(0,eval)("this")}catch(e){"object"==typeof window&&(t=window)}e.exports=t},function(e,n){e.exports=function(e){return e.webpackPolyfill||(e.deprecate=function(){},e.paths=[],e.children||(e.children=[]),Object.defineProperty(e,"loaded",{enumerable:!0,get:function(){return e.l}}),Object.defineProperty(e,"id",{enumerable:!0,get:function(){return e.i}}),e.webpackPolyfill=1),e}},function(e,n,t){(function(e,r){var o;!function(i){var a=("object"==typeof e&&e&&e.exports,"object"==typeof r&&r);a.global!==a&&a.window;var s=function(e){this.message=e};(s.prototype=new Error).name="InvalidCharacterError";var u=function(e){throw new s(e)},d="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/",c=/[\t\n\f\r ]/g,l={encode:function(e){e=String(e),/[^\0-\xFF]/.test(e)&&u("The string to be encoded contains characters outside of the Latin1 range.");for(var n,t,r,o,i=e.length%3,a="",s=-1,c=e.length-i;++s<c;)n=e.charCodeAt(s)<<16,t=e.charCodeAt(++s)<<8,r=e.charCodeAt(++s),a+=d.charAt((o=n+t+r)>>18&63)+d.charAt(o>>12&63)+d.charAt(o>>6&63)+d.charAt(63&o);return 2==i?(n=e.charCodeAt(s)<<8,t=e.charCodeAt(++s),a+=d.charAt((o=n+t)>>10)+d.charAt(o>>4&63)+d.charAt(o<<2&63)+"="):1==i&&(o=e.charCodeAt(s),a+=d.charAt(o>>2)+d.charAt(o<<4&63)+"=="),a},decode:function(e){var n=(e=String(e).replace(c,"")).length;n%4==0&&(n=(e=e.replace(/==?$/,"")).length),(n%4==1||/[^+a-zA-Z0-9/]/.test(e))&&u("Invalid character: the string to be decoded is not correctly encoded.");for(var t,r,o=0,i="",a=-1;++a<n;)r=d.indexOf(e.charAt(a)),t=o%4?64*t+r:r,o++%4&&(i+=String.fromCharCode(255&t>>(-2*o&6)));return i},version:"0.1.0"};void 0===(o=function(){return l}.call(n,t,n,e))||(e.exports=o)}()}).call(this,t(5)(e),t(4))},function(e,n,t){"use strict";var r,o="function"==typeof Symbol&&"symbol"==typeof Symbol.iterator?function(e){return typeof e}:function(e){return e&&"function"==typeof Symbol&&e.constructor===Symbol&&e!==Symbol.prototype?"symbol":typeof e},i=function(){function e(e,n){for(var t=0;t<n.length;t++){var r=n[t];r.enumerable=r.enumerable||!1,r.configurable=!0,"value"in r&&(r.writable=!0),Object.defineProperty(e,r.key,r)}}return function(n,t,r){return t&&e(n.prototype,t),r&&e(n,r),n}}();Array.from||(function(e){return"function"==typeof e},r=Math.pow(2,53)-1,function(e){var n=function(e){var n=Number(e);return isNaN(n)?0:0!==n&&isFinite(n)?(n>0?1:-1)*Math.floor(Math.abs(n)):n}(e);return Math.min(Math.max(n,0),r)});var a=t(3).encodeConsentString,s=t(0).decodeConsentString,u=t(1).vendorVersionMap,d=/^[a-z]{2}$/,c=function(){function e(){var n=arguments.length>0&&void 0!==arguments[0]?arguments[0]:null;!function(e,n){if(!(e instanceof n))throw new TypeError("Cannot call a class as a function")}(this,e),this.created=new Date,this.lastUpdated=new Date,this.version=1,this.vendorList=null,this.vendorListVersion=null,this.cmpId=null,this.cmpVersion=null,this.consentScreen=null,this.consentLanguage=null,this.allowedPurposeIds=[],this.allowedVendorIds=[],n&&Object.assign(this,s(n))}return i(e,[{key:"getConsentString",value:function(){var e=!(arguments.length>0&&void 0!==arguments[0])||arguments[0];if(!this.vendorList)throw new Error("ConsentString - A vendor list is required to encode a consent string");return!0===e&&(this.lastUpdated=new Date),a({version:this.getVersion(),vendorList:this.vendorList,allowedPurposeIds:this.allowedPurposeIds,allowedVendorIds:this.allowedVendorIds,created:this.created,lastUpdated:this.lastUpdated,cmpId:this.cmpId,cmpVersion:this.cmpVersion,consentScreen:this.consentScreen,consentLanguage:this.consentLanguage,vendorListVersion:this.vendorListVersion})}},{key:"getMetadataString",value:function(){return a({version:this.getVersion(),created:this.created,lastUpdated:this.lastUpdated,cmpId:this.cmpId,cmpVersion:this.cmpVersion,consentScreen:this.consentScreen,vendorListVersion:this.vendorListVersion})}},{key:"getVersion",value:function(){return this.version}},{key:"getVendorListVersion",value:function(){return this.vendorListVersion}},{key:"setGlobalVendorList",value:function(e){if("object"!==(void 0===e?"undefined":o(e)))throw new Error("ConsentString - You must provide an object when setting the global vendor list");if(!e.vendorListVersion||!Array.isArray(e.purposes)||!Array.isArray(e.vendors))throw new Error("ConsentString - The provided vendor list does not respect the schema from the IAB EU’s GDPR Consent and Transparency Framework");this.vendorList={vendorListVersion:e.vendorListVersion,lastUpdated:e.lastUpdated,purposes:e.purposes,features:e.features,vendors:e.vendors.slice(0).sort(function(e,n){return e.id<n.id?-1:1})},this.vendorListVersion=e.vendorListVersion}},{key:"setCmpId",value:function(e){this.cmpId=e}},{key:"getCmpId",value:function(){return this.cmpId}},{key:"setCmpVersion",value:function(e){this.cmpVersion=e}},{key:"getCmpVersion",value:function(){return this.cmpVersion}},{key:"setConsentScreen",value:function(e){this.consentScreen=e}},{key:"getConsentScreen",value:function(){return this.consentScreen}},{key:"setConsentLanguage",value:function(e){if(!1===d.test(e))throw new Error("ConsentString - The consent language must be a two-letter ISO639-1 code (en, fr, de, etc.)");this.consentLanguage=e}},{key:"getConsentLanguage",value:function(){return this.consentLanguage}},{key:"setPurposesAllowed",value:function(e){this.allowedPurposeIds=e}},{key:"getPurposesAllowed",value:function(){return this.allowedPurposeIds}},{key:"setPurposeAllowed",value:function(e,n){var t=this.allowedPurposeIds.indexOf(e);!0===n?-1===t&&this.allowedPurposeIds.push(e):!1===n&&-1!==t&&this.allowedPurposeIds.splice(t,1)}},{key:"isPurposeAllowed",value:function(e){return-1!==this.allowedPurposeIds.indexOf(e)}},{key:"setVendorsAllowed",value:function(e){this.allowedVendorIds=e}},{key:"getVendorsAllowed",value:function(){return this.allowedVendorIds}},{key:"setVendorAllowed",value:function(e,n){var t=this.allowedVendorIds.indexOf(e);!0===n?-1===t&&this.allowedVendorIds.push(e):!1===n&&-1!==t&&this.allowedVendorIds.splice(t,1)}},{key:"isVendorAllowed",value:function(e){return-1!==this.allowedVendorIds.indexOf(e)}}],[{key:"decodeMetadataString",value:function(e){var n=s(e),t={};return u[n.version].metadataFields.forEach(function(e){t[e]=n[e]}),t}}]),e}();e.exports={ConsentString:c}},function(e,n,t){"use strict";"function"==typeof Symbol&&Symbol.iterator;var r,o=(Array.from||(function(e){return"function"==typeof e},r=Math.pow(2,53)-1,function(e){var n=function(e){var n=Number(e);return isNaN(n)?0:0!==n&&isFinite(n)?(n>0?1:-1)*Math.floor(Math.abs(n)):n}(e);return Math.min(Math.max(n,0),r)},function(e){var n=e.next();return!Boolean(n.done)&&n}),t(7).ConsentString),i=t(0).decodeConsentString,a=t(3).encodeConsentString;e.exports={ConsentString:o,decodeConsentString:i,encodeConsentString:a}}]);

var Primis_BitString=function(str,bitsMap){if(this.string=str,this.bitsLen=8*str.length,this.bitsMap=bitsMap,this.fields={},this.bitPos=-1,this.binaryArr=[],"string"==typeof this.string){this.binaryArr=new Uint8Array(this.string.length);for(var i=0,len=this.string.length;i<len;i++)this.binaryArr[i]=255&this.string.charCodeAt(i)}this.read=function(){if("string"!=typeof this.string)return!1;if(this.string)for(var fieldName in this.bitsMap)if(this.bitsMap.hasOwnProperty(fieldName)&&Array.isArray(this.bitsMap[fieldName])&&this.bitsMap[fieldName].length&&(this.fields[fieldName]=this.readData(-1,this.bitsMap[fieldName][0],1<this.bitsMap[fieldName].length?this.bitsMap[fieldName][1]:Primis_BitString.FIELD_TYPE_INT),!1===this.fields[fieldName]))return!1;return!0},this.readData=function(bitOffset,numOfBits,dataType,isAllowPartialData){if(dataType==Primis_BitString.FIELD_TYPE_STRING&&numOfBits%8)return!1;if(dataType==Primis_BitString.FIELD_TYPE_STRING_6BIT&&numOfBits%6)return!1;-1==bitOffset&&(bitOffset=-1==this.bitPos?0:this.bitPos);for(var start_byte=Math.floor(bitOffset/8),end_byte=Math.floor((bitOffset+numOfBits-1)/8),bitsArr=[],currBit=8*start_byte,i=start_byte;i<=end_byte;i++)for(var j=7;0<=j&&(bitOffset<=currBit&&currBit<bitOffset+numOfBits&&(bitsArr.push(this.binaryArr[i]>>j&1),this.bitPos=currBit),!(bitOffset+numOfBits<=++currBit));j--);if(bitsArr&&this.bitPos++,!isAllowPartialData&&currBit<bitOffset+numOfBits)return!1;var res=!1;switch(dataType){case Primis_BitString.FIELD_TYPE_INT:for(res=0,i=0;i<bitsArr.length;i++)res=2*res+bitsArr[i];break;case Primis_BitString.FIELD_TYPE_BIT_ARRAY:res=[];for(i=0;i<bitsArr.length;i++)res.push(bitsArr[i]);break;case Primis_BitString.FIELD_TYPE_STRING:case Primis_BitString.FIELD_TYPE_STRING_6BIT:res="";var charSize=8,isOffsetFrom_a=!1,asciiA="a".charCodeAt(0);dataType==Primis_BitString.FIELD_TYPE_STRING_6BIT&&(charSize=6,isOffsetFrom_a=!0);for(i=0;i<bitsArr.length;i+=charSize){for(var charCode=0,j=0;j<charSize;j++)charCode=(charCode<<1)+bitsArr[i+j];res+=String.fromCharCode(isOffsetFrom_a?asciiA+charCode:charCode)}}return res},this.getFields=function(){var fieldName,isEmpty=!0;for(fieldName in this.fields)if(this.fields.hasOwnProperty(fieldName)){isEmpty=!1;break}return!isEmpty&&this.fields};try{this.read()}catch{}};Primis_BitString.FIELD_TYPE_INT=0,Primis_BitString.FIELD_TYPE_STRING=1,Primis_BitString.FIELD_TYPE_STRING_6BIT=2,Primis_BitString.FIELD_TYPE_BIT_ARRAY=3;
var Primis_TCString=function(tcString){this.tcString=tcString,this.coreStringProps={},this.vendors={},this.purposes={},this.vendorsIsRange=!1,this.base64url_decode=function(data){if(!data)return data;for(var o1,o2,h3,h4,bits,b64="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=",i=0,ac=0,tmp_arr=[];o1=(bits=b64.indexOf(data.charAt(i++))<<18|b64.indexOf(data.charAt(i++))<<12|(h3=b64.indexOf(data.charAt(i++)))<<6|(h4=b64.indexOf(data.charAt(i++))))>>16&255,o2=bits>>8&255,bits=255&bits,tmp_arr[ac++]=64==h3?String.fromCharCode(o1):64==h4?String.fromCharCode(o1,o2):String.fromCharCode(o1,o2,bits),i<data.length;);return tmp_arr.join("")},this.parse=function(){if("string"!=typeof this.tcString||!this.tcString)return!1;var tcParts=this.tcString.split(".",2);if(!tcParts)return!1;if(tcParts[0]=this.base64url_decode(tcParts[0]),1<tcParts.length&&(tcParts[1]=this.base64url_decode(tcParts[1])),coreStringParser=new Primis_BitString(tcParts[0],{Version:[6],Created:[36],LastUpdated:[36],CmpId:[12],CmpVersion:[12],ConsentScreen:[6],ConsentLanguage:[12,Primis_BitString.FIELD_TYPE_STRING_6BIT],VendorListVersion:[12],TcfPolicyVersion:[6],IsServiceSpecific:[1],UseNonStandardTexts:[1],SpecialFeatureOptIns:[12],PurposesConsent:[24,Primis_BitString.FIELD_TYPE_BIT_ARRAY],PurposesLITransparency:[24,Primis_BitString.FIELD_TYPE_BIT_ARRAY],PurposeOneTreatment:[1],PublisherCC:[12,Primis_BitString.FIELD_TYPE_STRING_6BIT],MaxVendorId:[16],IsRangeEncoding:[1]}),this.coreStringProps=coreStringParser.getFields(),!this.coreStringProps)return!1;if(!this.coreStringProps.PurposesConsent||!this.coreStringProps.PurposesConsent.length)return!1;for(var i=0;i<this.coreStringProps.PurposesConsent.length;i++)this.coreStringProps.PurposesConsent[i]&&(this.purposes[i+1]=this.coreStringProps.PurposesConsent[i]);if(this.coreStringProps.IsRangeEncoding){this.vendorsIsRange=!0;var numOfEntries=coreStringParser.readData(-1,12,Primis_BitString.FIELD_TYPE_INT);if(!numOfEntries)return!1;for(i=0;i<numOfEntries;i++){var isARange=coreStringParser.readData(-1,1,Primis_BitString.FIELD_TYPE_INT),startOrOnlyVendorId=coreStringParser.readData(-1,16,Primis_BitString.FIELD_TYPE_INT);if(isARange){var endVendorId=coreStringParser.readData(-1,16,Primis_BitString.FIELD_TYPE_INT);if(!endVendorId)return!1;for(var j=startOrOnlyVendorId;j<=endVendorId;j++)this.vendors[j]=1}else this.vendors[startOrOnlyVendorId]=1}}else{var vendorBits=coreStringParser.readData(-1,this.coreStringProps.MaxVendorId,Primis_BitString.FIELD_TYPE_BIT_ARRAY);if(!vendorBits||!vendorBits.length)return!1;for(i=0;i<vendorBits.length;i++)vendorBits[i]&&(this.vendors[i+1]=vendorBits[i])}},this.getPurposes=function(){return this.purposes},this.getVendors=function(){return this.vendors},this.isPurposesAllowed=function(purposes){if(!Array.isArray(purposes)||!purposes.length)return!1;try{for(var i=0;i<purposes.length;i++)if(!this.purposes[purposes[i]])return!1}catch{return!1}return!0},this.isVendorsAllowed=function(vendors){if(!Array.isArray(vendors)||!vendors.length)return!1;try{for(var i=0;i<vendors.length;i++)if(!this.vendors[vendors[i]])return!1}catch{return!1}return!0};try{this.parse()}catch(e){}};
/* GPP Implementation - Global Privacy Platform */
var SekindoClientDetections_GPP = function (isDebug, globalTimeout, onConsentAvail, isApp, gdprExpected = false, ccpaExpected = false) {
	this.SUPPORTED_VERSIONS = ['1.0', '1.1'];
	this.CONSENT_STILL_RUNNING = -1;
	this.CONSENT_REJECTED = 0;
	this.CONSENT_APPROVED = 1;
	this.CONSENT_NOT_APPLY = 2;
	this.CONSENT_FINISH = 3;
	this.PRIVACY_DETECTION_TIMEOUT_STEP_MS = 50;
	this.isGppLoaded = false;
	this.consentState = this.CONSENT_STILL_RUNNING;
	this.consentRawData = null;
	this.consentsData = {
		gdpr: {
			state: this.CONSENT_STILL_RUNNING,
			consent: ''
		},
		ccpa: {
			state: this.CONSENT_STILL_RUNNING,
			consent: ''
		}
	};
	this.debug = isDebug;
	this.requestTimeout = globalTimeout;
	this.isApp = isApp;
	this.startTs = new Date().getTime();
	this.gppCallsList = {};
	this.isListenerActive = false;
	this.isCallbackCalled = false;
	this.sectionsToVerify = ['tcfeuv2', 'uspv1'];
	this.TCF_EU_SECTION_ID = 2;
	this.USP_SECTION_ID = 6;
	this.GDPR_VENDOR_ID = 228;
	this.GDPR_PURPOSES = [1, 2, 5, 6, 7, 8];
	this.CCPA_VERSION = 1;
	this.applicableSections = [];
	this.gdprExpected = !!gdprExpected;
	this.ccpaExpected = !!ccpaExpected;

	if (onConsentAvail && typeof onConsentAvail == 'function') {
		this.onConsentAvail = onConsentAvail;
	}
	else
	{
		this.onConsentAvail = null;
	}

	this.getState = function () {
		return this.consentState;
	};

	this.getConsent = function () {
		return this.consentRawData ? this.consentRawData : '';
	};

	this._clearMessages = function (filterCallId) {
		for (const callId in this.gppCallsList)
		{
			if (filterCallId && callId != filterCallId)
				continue;
			if (!this.gppCallsList.hasOwnProperty(callId))
				continue;
			if (typeof this.gppCallsList[callId].cb === 'function')
				window.removeEventListener('message', this.gppCallsList[callId].cb);
			delete this.gppCallsList[callId];
		}
	};

	this._getSectionConsentStringFromGpp = function (section, availableSectionsApis, gppConsentStringParts) {
		let sectionConsentString = '';
		const index = availableSectionsApis.findIndex(function (availableSection) {
			const parts = availableSection.split(':');
			return parts.length > 1 && parts[1] === section;
		});
		if (index !== undefined && index !== -1) {
			sectionConsentString = gppConsentStringParts[index + 1] || '';
			if (this.debug) {
				console.log(`SEKDBG/GPP: parsed raw consent ${sectionConsentString} for section ${section}`);
			}
		}

		return sectionConsentString;
	};

	this._markAsNotApplied = function () {
		this.consentState = this.CONSENT_NOT_APPLY;
		this.consentsData.gdpr.state = this.CONSENT_NOT_APPLY;
		this.consentsData.ccpa.state = this.CONSENT_NOT_APPLY;
	};

	this._markAsValidationFailed = function () {
		this.consentState = this.CONSENT_FINISH;
		this.consentsData.gdpr.state = this.CONSENT_REJECTED;
		this.consentsData.ccpa.state = this.CONSENT_APPROVED;
	};

	this._verifyGppString = function (gppString) {
		const isString = typeof gppString === 'string';
		if (!isString) {
			return false;
		}

		const gppParts = gppString.split('~');
		return gppParts.length > 1 && gppParts.slice(1).some(part => part.trim().length > 0);
	};

	this._verify = function (pingData) {
		if (this.consentRawData == pingData.gppString && this.consentState != this.CONSENT_STILL_RUNNING) {
			return;
		}

		const sections = pingData.parsedSections || {};
		const applicableSections = pingData.applicableSections || [];

		if (this.debug) {
			console.log("SEKDBG/GPP: Full GPP string: " + pingData.gppString);
		}

		if (!this._verifyGppString(pingData.gppString)) {
			if (this.debug) {
				console.log("SEKDBG/GPP: Invalid GPP string (not a string, or no available sections after header)");
			}

			this._markAsValidationFailed();
			return;
		}

		const gppApplies = Array.isArray(applicableSections) && applicableSections.length > 0 && !(applicableSections.length === 1 && applicableSections[0] == -1);
		if (!gppApplies) {
			if (this.debug) {
				console.log("SEKDBG/GPP: No regulation applies (Global/None)");
			}

			this._markAsNotApplied();
			return;
		}

		const hasNonIntegerSection = applicableSections.some(id => !id || !Number.isInteger(Number(id)));
		if (hasNonIntegerSection) {
			if (this.debug) {
				console.log("SEKDBG/GPP: Applicable sections contain non-integer values");
			}

			this._markAsValidationFailed();
			return;
		}

		if (!pingData.gppVersion || !this.SUPPORTED_VERSIONS.includes(pingData.gppVersion)) {
			if (this.debug) {
				console.log("SEKDBG/GPP: Unsupported protocol version");
			}

			this._markAsValidationFailed();
			return;
		}

		if (!pingData.parsedSections || Object.keys(pingData.parsedSections).length === 0) {
			this.consentState = this.CONSENT_STILL_RUNNING;
			if (this.debug) {
				console.log("SEKDBG/GPP: Sections not presented");
			}

			return;
		}

		const activeRelevantSections = this.sectionsToVerify.filter(section =>
			pingData.parsedSections && pingData.parsedSections.hasOwnProperty(section)
		);

		if (activeRelevantSections.length == 0) {
			if (this.debug) {
				console.log("SEKDBG/GPP: Regulation applies, but not TCF or USP. Skipping check.");
			}

			this._markAsValidationFailed();
			return;
		}

		if (this.gdprExpected) {
			const hasTcf = applicableSections.indexOf(this.TCF_EU_SECTION_ID) !== -1 && sections.hasOwnProperty('tcfeuv2');
			if (!hasTcf) {
				if (this.debug) {
					console.log("SEKDBG/GPP: GDPR region expected but TCF section is missing from sid and parsed sections");
				}

				this._markAsValidationFailed();
				return;
			}
		}

		if (this.ccpaExpected) {
			const hasUsp = applicableSections.indexOf(this.USP_SECTION_ID) !== -1 && sections.hasOwnProperty('uspv1');
			if (!hasUsp) {
				if (this.debug) {
					console.log("SEKDBG/GPP: CCPA region expected but USP section is missing from sid and parsed sections");
				}

				this._markAsValidationFailed();
				return;
			}
		}

		this.consentRawData = pingData.gppString;
		this.applicableSections = applicableSections;

		this.consentsData.gdpr.state = sections.hasOwnProperty('tcfeuv2') ? this.consentsData.gdpr.state : this.CONSENT_NOT_APPLY;
		this.consentsData.ccpa.state = sections.hasOwnProperty('uspv1') ? this.consentsData.ccpa.state : this.CONSENT_NOT_APPLY;

		const availableSectionsApis = (pingData.supportedAPIs || []).filter((availableSection) => {
			const parts = availableSection.split(':');
			const sectionId = parseInt(parts[0]);
			return !isNaN(sectionId) && pingData.applicableSections.includes(sectionId);
		});

		const gppConsentStringParts = pingData.gppString.split('~');
		if (sections['tcfeuv2']) {
			this._verifyGdprSection(sections['tcfeuv2']);
			this.consentsData.gdpr.consent = this._getSectionConsentStringFromGpp('tcfeuv2', availableSectionsApis, gppConsentStringParts);
		}
		if (sections['uspv1']) {
			this._verifyCcpaSection(sections['uspv1']);
			this.consentsData.ccpa.consent = this._getSectionConsentStringFromGpp('uspv1', availableSectionsApis, gppConsentStringParts);
		}

		this.consentState = this._getOverallConsentState();
	};

	this._verifyGdprSection = function (sectionData) {
		if (!sectionData || !sectionData.VendorConsents || !sectionData.PurposeConsents) {
			this.consentsData.gdpr.state = this.CONSENT_REJECTED;
			if (this.debug) {
				console.log("SEKDBG/GPP-GDPR: GPP section data is missing - rejected by system");
			}
			return;
		}

		if (!sectionData.VendorConsents.includes(this.GDPR_VENDOR_ID)) {
			if (this.debug) {
				console.log("SEKDBG/GPP-GDPR: Vendor rejected by client");
			}

			this.consentsData.gdpr.state = this.CONSENT_REJECTED;
			return;
		}

		for (const purposeId of this.GDPR_PURPOSES) {
			if (!sectionData.PurposeConsents[purposeId]) {
				this.consentsData.gdpr.state = this.CONSENT_REJECTED;
				if (this.debug) {
					console.log("SEKDBG/GPP-GDPR: Purpose " + purposeId + " rejected by client");
				}
				return;
			}
		}

		if (this.debug) {
			console.log("SEKDBG/GPP-GDPR: Vendor approval received");
		}

		this.consentsData.gdpr.state = this.CONSENT_APPROVED;
	};

	this._verifyCcpaSection = function (sectionData) {
		if (!sectionData) {
			this.consentsData.ccpa.state = this.CONSENT_STILL_RUNNING;
			return;
		}

		const isStrictNotApplicable = (
			sectionData.Notice === '-' &&
			sectionData.OptOutSale === '-' &&
			sectionData.LspaCovered === '-'
		);

		if (isStrictNotApplicable) {
			if (this.debug) {
				console.log("SEKDBG/GPP-CCPA: CCPA does not apply (1--- equivalent)");
			}
			this.consentsData.ccpa.state = this.CONSENT_NOT_APPLY;
			return;
		}

		if (!sectionData.OptOutSale || sectionData.OptOutSale === '-') {
			this.consentsData.ccpa.state = this.CONSENT_STILL_RUNNING;
			return;
		}

		if (!sectionData.Version || sectionData.Version !== this.CCPA_VERSION) {
			if (this.debug) {
				console.log("SEKDBG/GPP-CCPA: Bad consent version is provided");
			}

			this.consentsData.ccpa.state = this.CONSENT_REJECTED;

			return;
		}

		if (sectionData.OptOutSale === 'Y') {
			this.consentsData.ccpa.state = this.CONSENT_REJECTED;
		}
		else
		{
			this.consentsData.ccpa.state = this.CONSENT_APPROVED;
		}
	};

	this._getOverallConsentState = function () {
		if (this.consentsData.ccpa.state == this.CONSENT_STILL_RUNNING || this.consentsData.gdpr.state == this.CONSENT_STILL_RUNNING) {
			return this.CONSENT_STILL_RUNNING;
		}
		return this.CONSENT_FINISH;
	};

	this._call = function (command, param) {
		const ref = this;
		const isEventListenerCmd = (command == 'addEventListener');
		if ((this.consentState != this.CONSENT_STILL_RUNNING || !this.gppCallbacksList.hasOwnProperty(command) ||
			typeof this.gppCallbacksList[command] !== 'function') && !isEventListenerCmd) {
			this._clearMessages();
			return;
		}

		const currTs = new Date().getTime();
		if (!isEventListenerCmd && currTs - ref.startTs >= this.requestTimeout) /* Timeout reached */ {
			if (this.debug) {
				console.log("SEKDBG/GPP: Timeout reached, no GPP found.");
			}

			this.consentState = this.CONSENT_NOT_APPLY;

			if (this.onConsentAvail && !this.isCallbackCalled) {
				this.onConsentAvail(this.consentRawData, {
					ccpa: false,
					gdpr: false,
					gdprConsentString: '',
					ccpaConsentString: '',
					gppSid: ''
				});
			}
			this._clearMessages();
			return;
		}

		if (!isEventListenerCmd && this.gppStopCallbacksList.hasOwnProperty(command) && typeof this.gppStopCallbacksList[command] === 'function'
			&& this.gppStopCallbacksList[command]()) {
			if (this.debug) {
				console.log("SEKDBG/GPP: Stopping "+command+" due to reached goals");
			}
			return;
		}

		try
		{
			window.top.__gpp(command, this.gppCallbacksList[command], param);
			if (ref.debug) {
				console.log("SEKDBG/GPP: Using DIRECT/"+command);
			}
		}
		catch (e)
		{
			if (ref.debug) {
				console.log("SEKDBG/GPP: Exception during DIRECT check");
				console.log(e);
			}
		}

		if (isEventListenerCmd) {
			return;
		}

		if (this.consentState == this.CONSENT_STILL_RUNNING && currTs - this.startTs < this.requestTimeout) {
			if (!this.gppStopCallbacksList.hasOwnProperty(command) || typeof this.gppStopCallbacksList[command] !== 'function' ||
				!this.gppStopCallbacksList[command]()) {
				setTimeout(function () {
					if (ref.debug) {
						console.log("SEKDBG/GPP: Reissuing command "+command+" to run again because consent is still not available.");
					}

					ref._call(command, param);
				}, this.PRIVACY_DETECTION_TIMEOUT_STEP_MS);
			}
			else
			{
				this._clearMessages();
			}
		}
		else
		{
			this._clearMessages();
		}
	};

	this.onGppLoaded = function (pingData) {
		if (!pingData || typeof pingData.gppString !== 'string') {
			this.consentState = this.CONSENT_STILL_RUNNING;
			return;
		}

		this._verify(pingData);

		if (this.onConsentAvail && (this.consentState == this.CONSENT_FINISH || this.consentState == this.CONSENT_NOT_APPLY) && !this.isCallbackCalled) {
			this.isCallbackCalled = true;
			this.onConsentAvail(this.consentRawData, {
				ccpa: (this.consentsData.ccpa.state == this.CONSENT_APPROVED || this.consentsData.ccpa.state == this.CONSENT_NOT_APPLY),
				gdpr: this.consentsData.gdpr.state == this.CONSENT_APPROVED,
				gdprConsentString: this.consentsData.gdpr.consent,
				ccpaConsentString: this.consentsData.ccpa.consent,
				gppSid: this.applicableSections.join(',')
			});
			this._clearMessages();
		}

		if (!this.isListenerActive) {
			this._call('addEventListener');
			this.isListenerActive = true;
		}
	};

	const ref = this;

	this.gppCallbacksList = {
		ping: function (result, success) {
			if (success && result && result.signalStatus == 'ready') {
				ref.isGppLoaded = true;
				if (ref.debug) {
					console.log("SEKDBG/GPP: GPP library is now fully loaded");
				}

				ref.onGppLoaded(result);
			} else if (ref.debug) {
				console.log("SEKDBG/GPP: GPP ping failed or returned no data");
			}
		},
		addEventListener: function (result) {
			if (!result) {
				return;
			}

			const isReadySignal = (result.eventName == 'signalStatus' && result.data == 'ready');
			const isSectionChanged = (result.eventName == 'sectionChange');
			if ((isReadySignal || isSectionChanged) && result.pingData && result.pingData.signalStatus == 'ready') {
				if (ref.debug) {
					console.log("SEKDBG/GPP: Event detected: " + result.eventName);
				}

				ref.onGppLoaded(result.pingData);
			}
		}
	};

	this.gppStopCallbacksList = {
		ping: function () {
			return ref.isGppLoaded;
		}
	};

	if (!this.isApp) {
		this._call('ping');
	}
};
var SekindoClientDynamicConfig = function (config, prob)
{
	this.MOBILE_MAX_WIDTH = 415;
	this.config = config;
	this.prob = prob;

	var ref = this;

	this.sizeSetup = function(rules)
	{
		var selectedRule = rules[rules.length-1];
		for (var i=0; i<rules.length-1; i++)
		{
			if (rules[i][0] <= ref.prob.window.width)
			{
				selectedRule = rules[i];
				break;
			}
		}

		ref.config.unit.width = selectedRule[0];
		ref.config.unit.height = selectedRule[1];
	};

	var compareObjectsByKeys = function(obj1, obj2)
	{
		for (var key in obj1)
		{
			if (typeof obj1[key] == "object" && obj2.hasOwnProperty(key) && typeof obj2[key] == "object")
			{
				if (!compareObjectsByKeys(obj1[key],obj2[key]))
				{
					return false;
				}
				continue;
			}
			if (!obj2.hasOwnProperty(key) || obj1[key] != obj2[key])
			{
				return false;
			}
		}
		return true;
	};
	
	this.clientInfoSetup = function(rules)
	{
		var clientInfoRule = rules[0];
		if (compareObjectsByKeys(clientInfoRule, ref.prob.ci))
		{
			var configRule = rules[1];
			for (var property in configRule)
			{
				ref.config[property] = configRule[property];
			}
		}
	};

	this.deviceTypeSetup = function(rules)
	{
		var selectedRule = rules[rules.length-1];
		for (var i=0; i<rules.length-1; i++)
		{
			if (rules[i][0].toLowerCase() == ref.prob.ci.deviceType.toLowerCase())
			{
				selectedRule = rules[i];
				break;
			}
		}

		ref.config.unit.width = selectedRule[1];
		ref.config.unit.height = selectedRule[2];

		if (selectedRule[3] != 'undefined' && selectedRule[3].length > 0)
		{
			var floatSetup = selectedRule[3];
			if (floatSetup[0] === 1)
			{
				if (!ref.isStickyVideoType())
				{
					ref.config.videoType = 'flow';
				}
			}
			else
			{
				if (ref.isStickyVideoType())
				{
					ref.config.url += '&blockAlwaysSticky=1';
				}
				ref.config.videoType = 'normal';
			}

			ref.config.floatConfig.width = floatSetup[1];
			ref.config.floatConfig.height = floatSetup[2];
			ref.config.floatConfig.direction = floatSetup[3];
			ref.config.floatConfig.verticalOffset = floatSetup[4];
			ref.config.floatConfig.horizontalOffset = floatSetup[5];
			ref.config.floatConfig.isCloseBtn = floatSetup[6];
		}
	};

	this.tabletFloatSetup = function(rules)
	{
		if (rules[0].toLowerCase() == ref.prob.ci.deviceType.toLowerCase())
		{
			if (rules[1][0] === 1)
			{
				var floatSetup = rules[1];
				if (!ref.isStickyVideoType())
				{
					ref.config.videoType = 'flow';
				}
				ref.config.floatConfig.width = floatSetup[1];
				ref.config.floatConfig.height = floatSetup[2];
				ref.config.floatConfig.direction = floatSetup[3];
				ref.config.floatConfig.verticalOffset = floatSetup[4];
				ref.config.floatConfig.horizontalOffset = floatSetup[5];
				ref.config.floatConfig.isCloseBtn = floatSetup[6];
				ref.config.floatConfig.flowMode = floatSetup[7];
				ref.config.floatConfig.closeBtnPos = floatSetup[8];
			}
			else
			{
				if (ref.isStickyVideoType())
				{
					ref.config.url += '&blockAlwaysSticky=1';
				}
				ref.config.videoType = 'normal';
			}
		}
	}

	this.sliderSetup = function(rules)
	{
		var selectedRule = rules[rules.length-1];
		for (var i=0; i<rules.length-1; i++)
		{
			if (rules[i][0] <= ref.prob.window.width)
			{
				selectedRule = sizes[i];
				break;
			}
		}

		ref.config.unit.width = selectedRule[0];
		ref.config.unit.height = selectedRule[1];
	}

	this.floatSetupSetDefaults = function (selectedRule)
	{
		// Floating display timeout after close float button has clicked
		if (typeof selectedRule['flowCloseTimeout'] === 'undefined' || selectedRule['flowCloseTimeout'] === '')
		{
			selectedRule['flowCloseTimeout'] = 0;
		}
		// Floating close button position
		if (typeof selectedRule['closeBtnPos'] === 'undefined' || selectedRule['closeBtnPos'] != 'left')
		{
			selectedRule['closeBtnPos'] = 'right';
		}
		return selectedRule;
	}
	
	this.floatSetupSelectRule = function (rules)
	{
		var selectedRule = rules[rules.length-1];
		for (var i=0; i<rules.length-1; i++)
		{
			if (rules[i]['screenWidthSize'] < ref.prob.window.width)
			{
				if (typeof rules[i]['screenHeightSize'] !== 'undefined' && rules[i]['screenHeightSize'] != -1)
				{
					if (rules[i]['screenHeightSize'] < ref.prob.window.height)
					{
						selectedRule = rules[i];
						break;
					}
					else
					{
						continue;
					}
				}
				else
				{
					selectedRule = rules[i];
					break;
				}
			}
		}
		return ref.floatSetupSetDefaults(selectedRule);
	}
	
	this.floatSetup = function(rules)
	{
		var selectedRule = ref.floatSetupSelectRule(rules);
		
		if (selectedRule['enabled'] === 1)
		{
			if (!ref.isStickyVideoType() && !ref.isSliderVideoType())
			{
				ref.config.videoType = 'flow';
			}
		}
		else
		{
			if (ref.isStickyVideoType())
			{
				ref.config.url += '&blockAlwaysSticky=1';
			}
			ref.config.videoType = 'normal';
		}

		ref.config.floatConfig = selectedRule;
		
		// Allow floating for only given GEO code
		if (typeof selectedRule['allowFloatingGeo'] !== 'undefined' && selectedRule['allowFloatingGeo'] !== '' && selectedRule['allowFloatingGeo'].indexOf(ref.prob.geo) == -1 && selectedRule['allowFloatingGeo'].indexOf('ALL_GEO') == -1)
		{
			ref.config.videoType = 'normal';
		}

		// Prevent floating for given GEO code
		if (typeof selectedRule['disallowFloatingGeo'] !== 'undefined' && selectedRule['disallowFloatingGeo'] !== '' && selectedRule['disallowFloatingGeo'].indexOf(ref.prob.geo) != -1 && selectedRule['disallowFloatingGeo'].indexOf('NO_DISALLOW_GEO') == -1)
		{
			ref.config.videoType = 'normal';
		}

		// Prevent floating for given DMA code
		if (typeof selectedRule['dmaList'] !== 'undefined' && selectedRule['dmaList'].indexOf(ref.prob.dmaCode) != -1)
		{
			ref.config.videoType = 'normal';
		}
	}

	this.clientSideSetup = function (rules) {
		var clientSideRules = rules[0];
		var configRule = rules[1];
		for (var clientProperty in clientSideRules)
		{
			if (eval(clientProperty) == clientSideRules[clientProperty])
			{
				for (var property in configRule)
				{
					ref.config[property] = configRule[property];
				}
			}
		}
	}

	this.playerDivSetup = function(rules)
	{
		if (typeof rules.mainElement !== 'undefined' && rules.mainElement["type"] && rules.mainElement["name"])
		{
			if (rules.mainElement["type"] == "id")
			{
				ref.config.playerDivSetup.elmtId = rules.mainElement["name"];
			}
			else if (rules.mainElement["type"] == "class")
			{
				ref.config.playerDivSetup.elmtClassName = rules.mainElement["name"];
			}
			else if (rules.mainElement["type"] == "querySelector")
			{
				ref.config.playerDivSetup.querySelector = rules.mainElement["name"];
			}

			if (typeof rules.mainElementNumber !== 'undefined')
			{
				ref.config.playerDivSetup.mainElementNumber = rules.mainElementNumber;
			}

			if (typeof rules.childElement !== 'undefined')
			{
				if (rules.childElement["type"] == "id")
				{
					ref.config.playerDivSetup.childElement = {};
					ref.config.playerDivSetup.childElement.elmtId = rules.childElement["name"];
				}
				else if (rules.childElement["type"] == "class")
				{
					ref.config.playerDivSetup.childElement = {};
					ref.config.playerDivSetup.childElement.elmtClassName = rules.childElement["name"];
				}
			}

			if (typeof rules.childElementNumber !== 'undefined')
			{
				ref.config.playerDivSetup.childElementNumber = rules.childElementNumber;
			}

			if (typeof rules.childElementTagName !== 'undefined')
			{
				ref.config.playerDivSetup.childElementTagName = rules.childElementTagName;
			}

			if (typeof rules.insertPosition !== 'undefined')
			{
				ref.config.playerDivSetup.insertPosition = rules.insertPosition;
			}
		}
	}

	this.newParamMapping = function(rules)
	{
		var selectedRule = rules[rules.length-1];
		for (var i=0; i<rules.length; i++)
		{
			var tagAdd='';
			var oldParam = rules[i][0];
			var newParam = rules[i][1];

			var regex = new RegExp("(\\?|&)"+oldParam+"\\=([^&]*)");
			var oldParamValue = ref.config.url.match(regex);
			if (oldParamValue && oldParamValue[2] != undefined)
			{
				ref.config.url += '&'+newParam+'='+oldParamValue[2];
			}
		}
	}

	this.splitDomain = function(rules)
	{
		if (!rules || !Array.isArray(rules) || rules.length === 0) {
			return;
		}
		
		var domainMap = rules[0];
		if (!domainMap || typeof domainMap !== 'object') {
			return;
		}
		
		var topDomain = '';
		var hostname = window.location.hostname;
		var parts = hostname.split('.');
		if (parts.length > 3) {
			topDomain = parts.slice(-3).join('.');
		}
		else
		{
			topDomain = parts.slice(-2).join('.');
		}
		
		if (topDomain != '' && domainMap.hasOwnProperty(topDomain) && document.currentScript && document.currentScript.parentElement)
		{
			var placementId = domainMap[topDomain];
			var url = new URL(document.currentScript.src);
			url.searchParams.set('s', placementId);
			var script = document.createElement('script');
			script.src = url.toString();
			document.currentScript.parentElement.insertBefore(script, document.currentScript);
			ref.config.url += '&blockPlacement=1';
		}
	}

	this.templateOverride = function(rules)
	{
		var overrideAllowed = true;
		if ((typeof rules.screenSize != 'undefined') && (typeof rules.screenSize[0] != 'undefined'))
		{
			overrideAllowed = ref.prob.window.width < rules.screenSize[0];
			if (overrideAllowed && (typeof rules.screenSize[1] != 'undefined'))
			{
				overrideAllowed = ref.prob.window.height < rules.screenSize[1];
			}
		}
		if (typeof rules.deviceType != 'undefined')
		{
			overrideAllowed = ref.prob.ci.deviceType.toLowerCase() == rules.deviceType.toLowerCase();
		}
		if (overrideAllowed && (typeof rules.newTemplateId != 'undefined'))
		{
			ref.config.vp_template = rules.newTemplateId;
		}
	}

	this.blockDomain = function (rules)
	{
		if (window.location && window.location.hostname && Array.isArray(rules) && rules.includes(window.location.hostname) && ref.config.url) {
			ref.config.url += '&blockPlacement=1';
		}
	}

	this.generalEmptyConfig = function (){}

	this.getDynamicConfigParams = function(i, deviceType)
	{
		var configEntity = '';
		var funcName = this.config.dynamicSetup[i][0];
		if (funcName === 'playerDivSetup' && this.config.dynamicSetup[i][1][0] && deviceType)
		{
			for (var j=0; j<this.config.dynamicSetup[i][1].length; j++)
			{
				if (this.config.dynamicSetup[i][1][j][deviceType])
				{
					configEntity = [funcName, this.config.dynamicSetup[i][1][j][deviceType]];
				}
			}
		}
		else
		{
			configEntity = [funcName, this.config.dynamicSetup[i][1]];
		}
		return configEntity;
	}

	this.run = function()
	{
		var deviceType = ref.prob.ci.deviceType.toLowerCase();
		for (var i=0; i<this.config.dynamicSetup.length; i++)
		{
			var dynamicConfigEntity = this.getDynamicConfigParams(i, deviceType);
			if (dynamicConfigEntity && dynamicConfigEntity[0] && dynamicConfigEntity[1])
			{
				try
				{
					var func = this.functionMap[dynamicConfigEntity[0]];
					func(dynamicConfigEntity[1]);
				}
				catch (e)
				{
					console.log(e.message);
				}
			}
		}
	}

	this.functionMap = {'sizeSetup' : this.sizeSetup,
						'floatSetup' : this.floatSetup,
						'deviceTypeSetup' : this.deviceTypeSetup,
						'tabletFloatSetup' : this.tabletFloatSetup,
						'playerDivSetup' : this.playerDivSetup,
						'clientInfoSetup' : this.clientInfoSetup,
						'clientSideSetup' : this.clientSideSetup,
						'newParamMapping' : this.newParamMapping,
						'templateOverride' : this.templateOverride,
						'playlistTargeting' : this.generalEmptyConfig,
						'blockDomain' : this.blockDomain,
						'splitDomain' : this.splitDomain
	};

	this.isStickyVideoType = function()
	{
		return ref.config.videoType == 'sticky';
	}

	this.isSliderVideoType = function()
	{
		return ref.config.videoType == 'slider';
	}
};
var SekindoClientDetections_URL = function (config) {
	/* Functions needed for constructor */
	this._getDiscoverableUrl = function()
	{
		var url = '';

		try
		{
			if (window.top == window)
			{
				url = window.location.href;
			}
			else
			{
				try
				{
					url = window.top.location.href;
				}
				catch (e2)
				{
					url = document.referrer;
				}
			}

			url = url.substring(0, 1500);
		}
		catch(e1) {}

		return url;
	}

	this._setCheckerWidget = function(allowedType)
	{
		switch (allowedType)
		{
			case "0":
				config.allowViewabilityCheck = false;
				config.allowUserScrollCheck  = false;
				break;

			case "1":
				config.allowViewabilityCheck = true;
				config.allowUserScrollCheck  = false;
				break;

			case "2":
				config.allowViewabilityCheck = false;
				config.allowUserScrollCheck  = true;
				break;
		}
	}

	this._initDebugCheck = function(config)
	{
		var debugParam, debugParamsRExp = RegExp('(\\?|&)(sekDbg_[^\=&]+)\=([^&]*)', 'gi');
		var pageUrl = this._getDiscoverableUrl();
		while ((paramMatch = debugParamsRExp.exec(pageUrl)) !== null)
		{
			debugParam = paramMatch[2].replace('sekDbg_', '');
			debugParam = debugParam.replace('sekdbg_', '');
			switch (debugParam)
			{
				case 'x':
					config.x = paramMatch[3];
					break;
				case 'y':
					config.y = paramMatch[3];
					break;
				case 'videoType':
					config.videoType = paramMatch[3];
					break;
				case 'perform':
					this._setCheckerWidget(paramMatch[3]);
					break;
				case 'log':
					config.debug = paramMatch[3];
					break;
			}
		};
	}

	/* Constructor */
	this._initDebugCheck(config);
	this.COOKIE_TIMEOUT = 7*24*60*60;
	this.VIDEO_HELPER_PARAM_NAME = 'videoHelperParam';
	this.VIDEO_SHARED_PARAM_NAME = config.sharedVideoParameterName;
	this.VIDEO_GAM_TARGETING_PARAM_NAME = config.gamTargetingVideoParameterName;

	this.floatConfig = config.floatConfig;
	this.videoType = config.videoType;
	this.frameInfo = {
		isInsideGoogleFrame: false,
		isBuildFrame: false,
		isBuildFrameViaJs : false
	};
	this.needWrappingIframe = config.needWrappingIframe;
	this.isAmpProject = config.isAmpProject;
	this.isAmpIframe = config.isAmpIframe;
	this.isAPI = config.isAPI;
	this.sizesList = config.sizesList;
	this.x = config.x;
	this.y = config.y;
	this.url = config.url;
	this.origQString = config.origQString;
	this.debug = config.debug;
	this.ci = config.ci;
	this.isFpCookie = config.isFpCookie;
	this.geo = config.geo;
	this.dmaCode = config.dmaCode;
	this.dynamicSetup = config.dynamicSetup;
	this.prob = {};
	this.uuid = config.uuid;
	this.isResponsiveBanner = config.isResponsiveBanner;
	this.hideOnMissingMainElement = config.hideOnMissingMainElement;
	this.allowedUtmParameters = config.allowedUtmParameters;
	this.placementId = config.placementId;
	this.allowDisplaySamePlacementAgain = config.allowDisplaySamePlacementAgain;
	this.blockOtherPlacements = config.blockOtherPlacements;
	this.searchByMetaTagName = config.searchMetaTagNames;
	this.customTargetingProperties = config.customTargetingProperties;
	this.customPpidMapping = config.customPpidMapping;
	this.helperParameters = {};
	this.placementType = config.placementType;
	this.isApp = config.isApp;
	this.rootWindow = null;
	this.elementChecker = {};
	this.observerElement = null;
	this.observedElementInfo   = {viewabilityThreshold:config.playerInViewPrc, isViewable:false, hasScrolled:false, lazyLoadFinished:false};
	this.allowViewabilityCheck = config.allowViewabilityCheck;
	this.allowUserScrollCheck  = config.allowUserScrollCheck;
	this.lazyLoad = config.lazyLoad;
	this.isIpad = false;
	this.isRun = config.isRun;
	this.isPlayerApiActions = config.isPlayerApiActions;
	this.isEnableGDPRListener = config.isEnableGDPRListener;
	this.isProcessFirstRun = true;
	this.gdprDetectionTimeout = config.gdprDetectionTimeout;
	this.gdprInfo = {
		v1: {
			consent: '',
			isWePass: 0,
			handler: null
		},
		v2: {
			consent: '',
			isWePass: 0,
			handler: null
		}
	};
	this.gppDetectionTimeout = config.gppDetectionTimeout;
	this.gppInfo = {
		consent: '',
		sid: '',
		handler: null,
		gdpr: {
			isWePass: 0,
			consent: ''
		},
		ccpa: {
			isRejected: 0,
			consent: ''
		}
	};
	this.isEnableGPPListener = config.isEnableGPPListener;
	this.isGppProcessFirstRun = true;
	this.consentCaptured = false;
	this._sharedBridgePromise = null;
	this.isBridgeOwner = !!window.isPrimisBridgeOwner;
	this.startTs = new Date().getTime();
	if (this.debug)
		console.log("SEKDBG: Starting timer towards timeout");

	this.getScriptElement = function()
	{
		if (typeof this.config.playerDivSetup.elmtClassName !== 'undefined' || typeof this.config.playerDivSetup.elmtId !== 'undefined' || typeof this.config.playerDivSetup.querySelector !== 'undefined')
		{
			try
			{
				if (this.debug)
				{
					console.log("SEKDBG: playerDivSetup config");
					console.log(this.config.playerDivSetup);
				}
				var specialElmt = this._getPlayerMainElement(window.top);
				if (specialElmt && typeof specialElmt !== 'undefined')
				{
					this.srcElement = specialElmt;
					if (this.debug)
					{
						console.log("SEKDBG: playerDivSetup element");
					}
					return;
				}
				if (typeof specialElmt === 'undefined' && this.hideOnMissingMainElement)
				{
					if (this.debug)
					{
						console.log("SEKDBG: Main element is missing");
					}
					this.srcElement = null;
					return;
				}
			}
			catch (e)
			{
				if (this.debug)
				{
					console.log("SEKDBG: playerDivSetup get specialElmt error - " + e.message);
				}
			}
		}

		if (document && typeof document.currentScript !== 'undefined')
		{
			if (this.debug)
				console.log("SEKDBG: currentScript is supported");
			this.srcElement = document.currentScript;
		}
		else if (document)
		{
			if (this.debug)
				console.log("SEKDBG: currentScript is not supported");
			try
			{
				/* IE 11 and below does not support currentScript */
				var scriptsList = [];
				if (typeof document.scripts !== 'undefined' && document.scripts)
				{
					if (this.debug)
						console.log("SEKDBG: document.scripts is supported");
					scriptsList = document.scripts;
				}
				else
				{
					if (this.debug)
						console.log("SEKDBG: document.scripts is not supported");
					scriptsList = document.getElementsByTagName('script');
				}
				for (var len = scriptsList.length, i = len; i >= 0; i --)
				{
					var scriptCandidate = scriptsList[i];
					if (scriptCandidate && scriptCandidate.src && scriptCandidate.src.indexOf(this.origQString) != -1)
					{
						this.srcElement = scriptCandidate;
						break;
					}
				}
			}
			catch (e)
			{
				this.srcElement = null;
			}
		}
	}

	this._getUuid = function()
	{
		if (this.url && this.url.includes('csuuid'))
		{
			return;
		}

		if (this.isFpCookie)
		{
			try
			{
				var uuid = window.document.cookie.replace(/(?:(?:^|.*;\s*)csuuidSekindo\s*\=\s*([^;]*).*$)|^.*$/, "$1");
				if (uuid != '')
				{
					this.uuid = uuid;
				}

				window.document.cookie = "csuuidSekindo="+ this.uuid +"; max-age=" + this.COOKIE_TIMEOUT + "; path=/";
			}
			catch (e)
			{
				this.uuid = null;
			}
		}
		else
		{
			this.uuid = null;
		}
		if (this.uuid != null)
		{
			this.url += '&csuuid=' + encodeURIComponent(this.uuid);
		}
	}

	this._handleDebugParams = function(param, value)
	{
		if (!param)
			return;
		param = param.replace('sekDbg_view_', '');
		switch (param)
		{
			case 'x':
				this.config.unit.width = value;
				break;
			case 'y':
				this.config.unit.height = value;
				break;
			case 'videoType':
				this.config.videoType = value;
				break;
			case 'flowMode':
				this.config.floatConfig.flowMode = value;
				break;
			case 'flowIsCloseBtn':
				this.config.floatConfig.isCloseBtn = value;
				break;
			case 'flowDirection':
				this.config.floatConfig.direction = value;
				break;
			case 'flowCloseButtonPosition':
				this.config.floatConfig.closeBtnPos = value;
				break;
		}
	}

	this._checkAvailCampaigns = function (pageUrl) {
		var matches = pageUrl.match(/(\?|&)availCampaigns\=([0-9,]*)([^0-9,]*)&?/i);
		if (matches && matches.length > 3 && matches[3] !== "")
			return "0";
		return (matches && matches.length > 1 && matches[2] ? matches[2] : null);
	}

	this._checkStartOverDebug = function(pageUrl)
	{
		const getParam = (p) => {
			let p_t = '';
			for (let lx = 0; lx < p.length; lx ++) {
				p_t += String.fromCharCode(p.charCodeAt(lx) + 2*((lx % 2) ? 1 : -1));
			}
			return p_t;
		}
		var dbgEp = this.isApp ? this.url.match(new RegExp(`[?&]${getParam('up2_r')}=([^&]+)(.*)?$`)) : pageUrl.match(new RegExp(`[?&]${getParam('up2_r')}=([^&]+)(.*)?$`));
		var addr = null;
		if (dbgEp && dbgEp.length > 1) {
			var debugServerValue = dbgEp[1].match(/^f(\d{3})$/);
			if (debugServerValue && debugServerValue.length > 1) {
				addr = debugServerValue[1] + getParam('0ntgogu+fcx,vcef');
			}
			else if (dbgEp[1].match(/^\d{3}$/)) { // Regular IP
				addr = getParam('3.039,4.0') + dbgEp[1];
			}
			else if (dbgEp[1].match(/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/)) {
				addr = dbgEp[1];
			}
			if (addr) {
				this.url = this.url.replace(`${getParam('ngxc0ntgogu,vcef')}`, addr).replace(`${getParam('ngxc0qgiklfm0aqk')}`, addr);
			}
		}

		if (!this.isApp) {
			var dbgUa = pageUrl.match(/[?&]dbgUa=([^&]*)/i);
			if (dbgUa) {
				this.url += '&dbgUa='+dbgUa[1];
			}
		}

		var debugId = pageUrl.match(/(\?|&)debugPlayerSession\=([^&]*)/i);
		if (debugId)
		{
			this.url = this.url+'&debugPlayerSession='+debugId[2];
		}

		var debugParamsRExp = RegExp('(\\?|&)(sekDbg_[^\=&]+)\=([^&]*)', 'g');
		while ((paramMatch = debugParamsRExp.exec(pageUrl)) !== null)
		{
			this.url = this.url+'&'+paramMatch[2]+'='+paramMatch[3];
			this._handleDebugParams(paramMatch[2], paramMatch[3]);
		};
	}

	this.setInfo = function()
	{
		var pageUrl = this._getDiscoverableUrl();

		this._checkStartOverDebug(pageUrl);
		this._checkDebugInformationUrlParam(pageUrl);
		this._checkTemplateUrlParam(pageUrl);

		if (this.config.unit.width == 0)
			return;

		var availCampaigns = this._checkAvailCampaigns(pageUrl);
		if (availCampaigns)
			this.url += '&availCampaigns=' + availCampaigns;

		if (this.isAmpProject || this.isAmpIframe) {
			this.url += '&pubUrlAuto=';// + encodeURIComponent(pageUrl);
		} else {
			this.url += '&pubUrlAuto=' + encodeURIComponent(pageUrl);
		}
		this.url = this.url.replace('SEKXLEN', this.config.unit.width);
		this.url = this.url.replace('SEKYLEN', this.config.unit.height);
		this.url = this.url.replace("'", '%27');

		if (!this.isEnableGDPRListener) {
			this._getUuid();
		}

		if (this.config.placementConfig)
		{
			for (var property in this.config.placementConfig)
			{
				this.url += '&' + property + '=' + this.config.placementConfig[property];
			}
		}

		if (this.config.videoType == 'normal')
		{
			this.url += '&videoType=normal';
		}
		else if (this.config.videoType == 'flow' || this.config.videoType == 'sticky' || this.config.videoType == 'slider')
		{
			this.url += '&videoType=' + this.config.videoType + '&floatWidth=' + this.config.floatConfig.width + '&floatHeight=' + this.config.floatConfig.height +
				'&floatDirection=' + this.config.floatConfig.direction + '&floatVerticalOffset=' + this.config.floatConfig.verticalOffset + '&floatHorizontalOffset=' + this.config.floatConfig.horizontalOffset +
				'&floatCloseBtn=' + this.config.floatConfig.isCloseBtn + '&flowMode='+this.config.floatConfig.flowMode + '&flowCloseButtonPosition=' + this.config.floatConfig.closeBtnPos;
		}

		if (typeof this.config.vp_template != 'undefined')
		{
			this._setReplaceUrlParam('vp_template', this.config.vp_template);
		}

		if (typeof this.config.vp_content != 'undefined')
		{
			this._setReplaceUrlParam('vp_content', this.config.vp_content);
		}

		if (this.allowedUtmParameters && this.allowedUtmParameters.length > 0)
		{
			this._setUtmParameters(pageUrl);
		}

		try
		{
			// We assume we are the only element/advertiser inside DFP iframe
			var w = window;
			this.rootWindow = w.parent;
			do
			{
				var wf = w.frameElement;
				while (wf != null)
				{
					if (wf.parentNode.id.indexOf('div-gpt-ad') != -1)
					{
						this.frameInfo.isInsideGoogleFrame = true;
						break;
					}
					wf = wf.parentNode;
				}
				w = w.parent;
			} while (w != w.parent);
			this.rootWindow = w;
			if (this.debug)
			{
				console.log("SEKDBG: [INFO] window element");
				console.log(w);
			}
		}
		catch(e)
		{
			if (this.debug)
			{
				console.log("SEKDBG: [INFO] " + e.name + ": " + e.message);
			}
		}
		try
		{
			if (!this.frameInfo.isInsideGoogleFrame)
			{
				if (window.frameElement.id.indexOf('google_ads_iframe') != -1)
				{
					this.frameInfo.isInsideGoogleFrame = true;
					this.frameInfo.googleFrameId = window.frameElement.id;
					if (this.debug)
					{
						console.log("SEKDBG: [INFO] frame ID: " + this.frameInfo.googleFrameId);
						console.log("SEKDBG: [INFO] parent element");
						console.log(this.rootWindow);
					}
				}
			}
		}
		catch (e)
		{
			if (this.debug)
			{
				console.log("SEKDBG: [INFO] - " + e.name + ": " + e.message);
			}
		}

		this.frameInfo.isBuildFrame = (this.needWrappingIframe && !this.frameInfo.isInsideGoogleFrame) || this.isAmpProject || (typeof this.config.playerDivSetup.elmtClassName !== 'undefined' || typeof this.config.playerDivSetup.elmtId !== 'undefined' || typeof this.config.playerDivSetup.querySelector !== 'undefined');
		/* Async exec requires isBuildFrame */
		// TODO:: should recognize and build iframe throgh JS also if document is ready/loaded
		this.frameInfo.isBuildFrameViaJs = (typeof this.config.playerDivSetup.elmtClassName !== 'undefined' || typeof this.config.playerDivSetup.elmtId !== 'undefined' || typeof this.config.playerDivSetup.querySelector !== 'undefined') || (this.frameInfo.isBuildFrame && this.srcElement && (this.srcElement.async || this.srcElement.defer)) || (this.frameInfo.isBuildFrame && (this.allowViewabilityCheck || this.allowUserScrollCheck));
		if (this.debug)
		{
			console.log("SEKDBG: [INFO] this.needWrappingIframe="+(this.needWrappingIframe ? 'yes' : 'no'));
			console.log("SEKDBG: [INFO] window.frameElement="+(window.frameElement ? 'ok' : 'n/a'));
			console.log("SEKDBG: [INFO] this.frameInfo.isBuildFrame="+(this.frameInfo.isBuildFrame ? 'yes' : 'no'));
			console.log("SEKDBG: [INFO] this.frameInfo.isInsideGoogleFrame="+(this.frameInfo.isInsideGoogleFrame ? 'yes' : 'no'));
			console.log("SEKDBG: [INFO] this.frameInfo.isBuildFrameViaJs="+(this.frameInfo.isBuildFrameViaJs ? 'yes' : 'no'));
			console.log("SEKDBG: [INFO] this.srcElement="+(this.srcElement ? 'ok' : 'n/a'));
			if (this.srcElement)
			{
				console.log("SEKDBG: [INFO] this.srcElement.async="+(this.srcElement.async ? 'yes' : 'no'));
				console.log("SEKDBG: [INFO] this.srcElement.defer="+(this.srcElement.defer ? 'yes' : 'no'));
			}
		}
		this._setBlockPlacementSettings(w.top);
		if (this.searchByMetaTagName)
		{
			var ref = this;
			Object.keys(this.searchByMetaTagName).forEach(function (idx)
			{
				if (typeof ref.searchByMetaTagName["tagAttribute"] === 'undefined')
				{
					// default meta tag attribute
					ref.searchByMetaTagName["tagAttribute"] = "name";
				}
				if (idx != "tagAttribute")
				{
					ref._setMetaTagHelperContent(w.top, ref.searchByMetaTagName["tagAttribute"], ref.searchByMetaTagName[idx], idx);
				}
			});
		}
		/* iPad client detection/set */
		if (this.isIpad)
		{
			this.url += '&pubDeviceType=Tablet';
			this.url += '&pubOs=iOS';
			this.url += '&pubOsVer=';
		}

		this._setSharedVideoParameter(pageUrl);
		this._setTargetingCustomParameter();
		this._setCustomPpid();
		this._setHelperParameters();
		this._setObserverChecker();
	}

	this._getTagContainerSizeInfo = function()
	{
		var containerInfo = [];
		var containerIframe = '';
		var iframeElement = null;
		containerInfo['urlParams'] = '&x=320&y=480';
		containerInfo['xLen'] = 320;
		containerInfo['yLen'] = 480;

		try
		{
			if (window.parent.document.querySelector('[id^=google_ads_iframe_dummy_sekindoParent]') != null)
			{
				containerIframe = window.parent.document.querySelector('[id^=google_ads_iframe_dummy_sekindoParent]').id;
				iframeElement = window.parent.document.getElementById(containerIframe);

				if (iframeElement.parentElement.parentElement.parentElement.clientWidth !== 0)
				{
					containerInfo['xLen'] = iframeElement.parentElement.parentElement.parentElement.clientWidth;
				}
				else if (iframeElement.parent.document.clientWidth !== 0)
				{
					containerInfo['xLen'] = iframeElement.parent.document.clientWidth;
				}

				if (iframeElement.parentElement.parentElement.parentElement.clientHeight !== 0)
				{
					containerInfo['yLen'] = iframeElement.parentElement.parentElement.parentElement.clientHeight;
				}
				else if (iframeElement.parent.document.clientHeight !== 0)
				{
					containerInfo['yLen'] = iframeElement.parent.document.clientHeight;
				}

				containerInfo['urlParams'] = '&x='+containerInfo['xLen']+'&y='+containerInfo['yLen'];
			}
			else if (this.frameInfo.isInsideGoogleFrame)
			{
				containerIframe = window.parent.document.querySelector('iframe[id^=google_ads_iframe]').id;
				iframeElement = window.parent.document.getElementById(containerIframe);
				containerInfo['urlParams'] = '&x='+iframeElement.clientWidth+'&y='+iframeElement.clientHeight;
			}
		}
		catch (e)
		{
			if (this.debug)
			{
				console.log("SEKDBG: Exception get DFP or Dummy iframe element");
			}
		}

		return containerInfo;
	}

	this._appendSharedBridgeReady = function()
	{
		if (!this.url.includes('sharedBridgeReady='))
		{
			this.url += '&sharedBridgeReady=1';
		}
	}

	this._prepareSharedBridge = function()
	{
		if (this._sharedBridgePromise)
			return this._sharedBridgePromise;

		var ref = this;
		this._sharedBridgePromise = (async function()
		{
			if (ref.videoType !== 'display')
				return;

			var bridge = null;
			try
			{
				bridge = window.top && window.top.PrimisBridge;
			}
			catch (e)
			{
				if (ref.debug)
					console.log("SEKDBG/BRIDGE: no access to window.top.PrimisBridge", e);
				return;
			}
			if (!bridge)
				return;

			try
			{
				if (bridge.status !== 'READY')
				{
					if (ref.isBridgeOwner)
						return;

					await Promise.race([
						bridge.waitUntilReady(),
						new Promise(function(resolve)
						{
							setTimeout(function()
							{
								if (ref.debug)
									console.log("SEKDBG/BRIDGE: wait timed out — proceeding");
								resolve();
							}, 6000);
						})
					]);
				}

				if (bridge.status === 'READY')
					ref._appendSharedBridgeReady();
			}
			catch (e)
			{
				if (ref.debug)
					console.log("SEKDBG/BRIDGE: prepare error", e);
			}
		})();

		return this._sharedBridgePromise;
	}


	this.process = async function()
	{
		if (!this.isRun)
			return;

		await this._prepareSharedBridge();

		const promises = [];
		if (this.isEnableGDPRListener && this.isProcessFirstRun) {
			promises.push(this.gdprConsentCheck().catch(e => {
				if (this.debug) {
					console.log("SEKDBG/GDPR: GDPR consent check failed", e);
				}
				return e;
			}));
		}
		if (this.isEnableGPPListener && this.isGppProcessFirstRun) {
			promises.push(this.gppConsentCheck().catch(e => {
				if (this.debug) {
					console.log("SEKDBG/GPP: GPP consent check failed", e);
				}
				return e;
			}));
		}

		await Promise.all(promises);

		if (this.config.unit.width == 0)
			return;
		if ((!this.observedElementInfo.isViewable && this.allowViewabilityCheck) || (!this.observedElementInfo.hasScrolled && this.allowUserScrollCheck) || (!this.observedElementInfo.lazyLoadFinished && this.lazyLoad))
			return;
		if (this.ci.browser == 'ie')
			return;

		var ref = this;
		var url = this.url;

		if (this.frameInfo.isBuildFrame)
		{
			var constructed = false;
			var uniqueID = 'sekindoParent'+Math.round(Math.random()*1000);
			window['construct'+uniqueID] = function (iframe)
			{
				if (constructed) return;
				constructed = true;
				if (iframe.contentWindow || iframe.contentDocument)
				{
					var iFramewindow = iframe.contentWindow || iframe.contentDocument.defaultView;
					var iFrameDoc = iFramewindow.document || iframe.contentDocument;

					if (ref.isResponsiveBanner)
					{
						var tagContainerSizeInfo = ref._getTagContainerSizeInfo();
						if (tagContainerSizeInfo['urlParams'] != '')
						{
							url += tagContainerSizeInfo['urlParams'];
							ref.config.unit.width = tagContainerSizeInfo['xLen'];
							ref.config.unit.height = tagContainerSizeInfo['yLen'];
						}
					}

					//Make dom ready.
					iFrameDoc.open();
					iFrameDoc.close();
					// If appendChild fails - go to document.write
					try
					{
						var script1 = iFrameDoc.createElement('script');
						script1.text = "window.baseIframeName = 'google_ads_iframe_dummy_" + uniqueID +"'"
						iFrameDoc.head.appendChild(script1);

						var base = document.createElement('base');
						base.href = 'https://amli.sekindo.com/';
						iFrameDoc.head.appendChild(base);

						var script = document.createElement('script');
						script.src = url;
						iFrameDoc.head.appendChild(script);
					}
					catch(e)
					{
						ref._docWrite(iFrameDoc, uniqueID, url);
					}
				}
			}

			if (this.frameInfo.isBuildFrameViaJs)
			{
				var iframe = document.createElement('iframe');
				var div0 = document.createElement('div');
				var div1 = document.createElement('div');
				div1.id = 'primisPlayerContainerDiv';

				iframe.marginWidth = '0';
				iframe.marginHeight = '0';
				iframe.hspace = '0';
				iframe.vspace = '0';
				if (this.isAPI) iframe.height = '0';
				iframe.frameBorder = '0';
				iframe.scrolling = 'no';
				iframe.title = 'Primis Frame';
				iframe.id = 'google_ads_iframe_dummy_'+uniqueID;
				iframe.style.width = '1px';
				iframe.style.height = '1px';

				if (typeof this.config.playerDivSetup !== 'undefined' && typeof this.config.playerDivSetup.insertPosition !== 'undefined')
				{
					if (this.config.playerDivSetup.insertPosition == "inside")
					{
						this.srcElement.appendChild(div0);
					}
					else if (this.config.playerDivSetup.insertPosition == "after")
					{
						this.srcElement.parentNode.insertBefore(div0, this.srcElement.nextElementSibling);
					}
					else if (this.config.playerDivSetup.insertPosition == "before")
					{
						this.srcElement.parentNode.insertBefore(div0, this.srcElement);
					}
				}
				else
				{
					if (this.srcElement)
					{
						this.srcElement.parentNode.insertBefore(div0, this.srcElement);
					}
				}
				div0.appendChild(div1);
				div1.appendChild(iframe);
				window['construct'+uniqueID](iframe);
			}
			else
			{
				var code = '<div><iframe style="width:1px; height:1px;"  marginwidth="0" marginheight="0" hspace="0" vspace="0" frameborder="0" scrolling="no" onload="construct'+uniqueID+'(this)" title ="Primis Frame" id ="google_ads_iframe_dummy_'+uniqueID+'"></iframe></div>';
				try
				{
					var div = document.createElement('div');
					div.innerHTML = code;
					var currScript = this.getCurrScript()
					currScript.parentNode.insertBefore(div, currScript);
				}
				catch(e)
				{
					code = '<div>'+code+'</div>';
					document.write(code);
				}
			}
		}
		else
		{
			if (ref.isResponsiveBanner)
			{
				var tagContainerSizeInfo = ref._getTagContainerSizeInfo();
				if (tagContainerSizeInfo['urlParams'] != '')
				{
					url += tagContainerSizeInfo['urlParams'];
				}
			}
			try
			{
				var script = document.createElement('script');
				script.src = url;
				document.head.appendChild(script);
			}
			catch(e)
			{
				document.write(unescape("%3Cscript src='") + url + unescape("' type='text/javascript'%3E%3C/script%3E"));
			}
		}
	}

	this.getCurrScript = function(element, checkLimit)
	{
		return document.currentScript || this.srcElement || document.scripts[document.scripts.length-1] ;
	};

	this._docWrite = function(iFrameDoc, uniqueID, url)
	{
		iFrameDoc.open();
		iFrameDoc.write(unescape("%3Cscript%3Evar baseIframeName = 'google_ads_iframe_dummy_") + uniqueID + unescape("'%3C/script%3E") + "<base href='https://amli.sekindo.com/'>" + unescape("%3Cscript src='") + url + unescape("' type='text/javascript'%3E%3C/script%3E"));
		iFrameDoc.close();
	}

	this._getPlayerMainElement = function(orgWin)
	{
		var sourceElmt;
		if (window.frameElement !== null)
		{
			var pdmt, contElmt, gfrm=window.frameElement.id;
			pdmt 	 = window.parent.document.getElementById(gfrm);
			contElmt = pdmt.parentNode.parentNode.parentNode; // element before DFP div
			orgWin   = contElmt.ownerDocument.defaultView || contElmt.ownerDocument.parentWindow;
		}
		try
		{
			if (this.debug)
			{
				console.log("SEKDBG: mainElement owner");
				console.log(orgWin);
			}
			sourceElmt = this._getSourceElementByType(orgWin.top.document, this.config.playerDivSetup);
		}
		catch (e)
		{
			if (this.debug)
			{
				console.log("SEKDBG: Exception get mainElement");
			}
			sourceElmt = this._getSourceElementByType(orgWin.document, this.config.playerDivSetup);
		}
		if (this.debug)
		{
			console.log("SEKDBG: playerDivSetup mainElement");
			console.log(sourceElmt);
		}

		if (sourceElmt && typeof sourceElmt !== 'undefined' && typeof this.config.playerDivSetup.childElement !== 'undefined')
		{
			sourceElmt = this._getSourceElementByType(sourceElmt, this.config.playerDivSetup.childElement);
			if (this.debug)
			{
				console.log("SEKDBG: playerDivSetup childElement");
				console.log(sourceElmt);
			}
		}

		if (typeof this.config.playerDivSetup.childElementNumber !== 'undefined' && typeof sourceElmt !== 'undefined')
		{
			if (typeof this.config.playerDivSetup.childElementTagName !== 'undefined')
			{
				sourceElmt = sourceElmt.getElementsByTagName(this.config.playerDivSetup.childElementTagName)[this.config.playerDivSetup.childElementNumber - 1];
			}
			else
			{
				for (var i = 0; i < sourceElmt.childElementCount; i++)
				{
					if (i == this.config.playerDivSetup.childElementNumber - 1)
					{
						sourceElmt = sourceElmt.children[i];
					}
				}
			}
		}
		return sourceElmt;
	}

	this._getSourceElementByType = function(orgWin, playerDivSetup)
	{
		var sourceElmt = null;
		if (typeof playerDivSetup.elmtClassName !== 'undefined')
		{
			if (typeof playerDivSetup.mainElementNumber !== 'undefined')
			{
				sourceElmt = orgWin.getElementsByClassName(playerDivSetup.elmtClassName)[playerDivSetup.mainElementNumber-1];
			}
			else
			{
				sourceElmt = orgWin.getElementsByClassName(playerDivSetup.elmtClassName)[0];
			}
		}
		else if (typeof playerDivSetup.elmtId !== 'undefined')
		{
			sourceElmt = orgWin.getElementById(playerDivSetup.elmtId);
		}
		else if (typeof playerDivSetup.querySelector !== 'undefined')
		{
			sourceElmt = orgWin.querySelector(this.config.playerDivSetup.querySelector);
		}
		return sourceElmt;
	}

	this._setUtmParameters = function(pageUrl)
	{
		var d_utm = '', ref = this;
		this.url = this.url.replace('&subId=[SUBID_ENCODED]','');
		if (pageUrl != '')
		{
			var parts = pageUrl.replace(/[?&#]+([^=&]+)=([^&]*)/gi, function(m,key,value) {
				for (var i = 0; i < ref.allowedUtmParameters.length; i++)
				{
					if (key.toLowerCase() == ref.allowedUtmParameters[i])
					{
						d_utm += '-'+value;
					}
				}
			});
			d_utm = d_utm.substring(1);
		}
		if (d_utm == '')
		{
			d_utm = 'default';
		}
		this.url += '&subId=' + d_utm;
	}

	this._setBlockPlacementSettings = function(orgWin) {
		if (this.placementId != -1) {
			try {
				var addBlockParameter = false;

				// Block same placement
				if (typeof orgWin.sekindoDisplayedPlacement === 'undefined') {
					orgWin.sekindoDisplayedPlacement = this.placementId;
					if (this.debug) {
						console.log("SEKDBG: Displayed placement: "+this.placementId);
					}
				}
				else if (!this.allowDisplaySamePlacementAgain && orgWin.sekindoDisplayedPlacement == this.placementId) {
					addBlockParameter = true;
					if (this.debug) {
						console.log("SEKDBG: Allow display the same placement: "+this.allowDisplaySamePlacementAgain);
						console.log("SEKDBG: Placement ID verification: "+this.placementId);
						console.log("SEKDBG: Displayed placement on page: "+orgWin.sekindoDisplayedPlacement);
					}
				}
				// Block other placements
				if (!addBlockParameter) {
					if (this.blockOtherPlacements && typeof orgWin.sekindoBlockOtherPlacements === 'undefined') {
						orgWin.sekindoBlockOtherPlacements = true;
						if (this.debug) {
							console.log("SEKDBG: Displayed placement: "+this.placementId);
						}
					}
					else if (orgWin.sekindoBlockOtherPlacements) {
						addBlockParameter = true;
						if (this.debug) {
							console.log("SEKDBG: Block other placements: "+this.blockOtherPlacements);
						}
					}
				}

				if (addBlockParameter) { // add block parameter to second call
					this.url += '&blockPlacement=1';
				}
			}
			catch (e) {}
		}
	};

	this._getMetaTagContent = function(orgWin, property, searchPropertyValue) {
		var tagContent = null;
		var metaTags = [];
		try {
			metaTags = orgWin.document.getElementsByTagName("meta");
		} catch (e) {}
		for (var idx = 0; idx < metaTags.length; idx++) {
			if (typeof metaTags[idx].getAttribute(property) !== 'undefined' && metaTags[idx].getAttribute(property) === searchPropertyValue) {
				if (typeof metaTags[idx].getAttribute("content") !== 'undefined') {
					tagContent = metaTags[idx].getAttribute("content");
					break;
				}
			}
		}
		return tagContent;
	};

	this._setMetaTagHelperContent = function(w, property, searchProperty, contentName)
	{
		var metaTagContent = this._getMetaTagContent(w, property, searchProperty);
		if (metaTagContent)
		{
			this.helperParameters[contentName] = metaTagContent;
		}
	};

	this._setHelperParameters = function()
	{
		if (Object.keys(this.helperParameters).length > 0)
		{
			// convert helper parameters object to JSON base64 encoded string
			var jsonFormattedHelperParameters = encodeURIComponent(JSON.stringify(this.helperParameters));
			this.url += '&'+this.VIDEO_HELPER_PARAM_NAME+'='+jsonFormattedHelperParameters;
		}
	};

	this._setSharedVideoParameter = function(pageUrl)
	{
		var s_content = '', ref = this;
		if (pageUrl != '')
		{
			var parts = pageUrl.replace(/[?&#]+([^=&]+)=([^&]*)/gi, function(m,key,value) {
				if (key.toLowerCase() == ref.VIDEO_SHARED_PARAM_NAME)
				{
					s_content = value;
				}
			});
		}
		if (s_content !== '' && s_content.indexOf("embed") != -1)
		{
			this.helperParameters[ref.VIDEO_SHARED_PARAM_NAME] = s_content;
		}
	};

	this._setTargetingCustomParameter = function()
	{
		var custom_parameters = {};
		if (this.customTargetingProperties && Object.keys(this.customTargetingProperties).length > 0)
		{
			if (typeof this.customTargetingProperties["objectType"] !== 'undefined' && typeof this.customTargetingProperties["objectFunction"] !== 'undefined')
			{
				// try parsing from json and decide function based on domain
				try {
					let isJson = JSON.parse(this.customTargetingProperties["objectFunction"]);
					if (typeof isJson === 'object' && isJson != null) {
						let url = this._getDiscoverableUrl();
						Object.keys(isJson).forEach((key) => {
							if (url.includes(key)) {
								this.customTargetingProperties["objectFunction"] = isJson[key];
							}
						});
					}
				}
				catch (e) {

				}
				try
				{
					custom_parameters = eval(this.customTargetingProperties["objectType"]+"."+this.customTargetingProperties["objectFunction"]);
					if (Object.keys(custom_parameters).length > 0)
					{
						if (typeof custom_parameters == 'string')
						{
							var tmp = {};
							tmp[this.customTargetingProperties["objectFunction"]] = [custom_parameters];
							custom_parameters = tmp;
						}
						this.helperParameters[this.VIDEO_GAM_TARGETING_PARAM_NAME] = custom_parameters;
					}
				}
				catch (e) {}
			}
		}
	};

	this._setCustomPpid = function() {
		if (this.customPpidMapping && Object.keys(this.customPpidMapping).length > 0) {
			var customPpidParameter = {};
			if (typeof this.customPpidMapping["objectType"] !== 'undefined' && typeof this.customPpidMapping["objectFunction"] !== 'undefined') {
				try {
					customPpidParameter = eval(this.customPpidMapping["objectType"]+"."+this.customPpidMapping["objectFunction"]);
					if (Object.keys(customPpidParameter).length > 0) {
						this.helperParameters['ppid'] = customPpidParameter;
					}
				}
				catch (e) {}
			}
		}
	};

	this._getViewportSize = function(w)
	{
		if (w.innerWidth != null)
			return {w:w.innerWidth, h:w.innerHeight};

		var d = w.document;
		if (document.compatMode == "CSS1Compat")
			return {w: d.documentElement.clientWidth, h: d.documentElement.clientHeight};

		return {w: d.body.clientWidth, h: d.body.clientWidth};
	};

	this._setProb = function()
	{
		try {
			viewPortSize = this._getViewportSize(window.top);
		}
		catch (e) {
			viewPortSize = this._getViewportSize(window);
		}

		this.prob.window = {};
		this.prob.window.width = viewPortSize.w;
		this.prob.window.height = viewPortSize.h;
		this.prob.geo = this.geo;
		this.prob.ci = this.ci;
		this.prob.ci.geo = this.geo;
		this.prob.dmaCode = this.dmaCode;
		this._setIpadConfig();
	}

	this._setIpadConfig = function()
	{
		try
		{
			if (this.url.indexOf('pubDeviceType') == -1 && navigator.platform === 'MacIntel' && navigator.maxTouchPoints >= 5 && typeof navigator.standalone !== "undefined")
			{
				this.isIpad = true;
				this.prob.ci.deviceType = "tablet";
			}
		}
		catch (e){}
	}

	this._setConfig = function()
	{
		this.config = {};
		this.config.unit = {};
		this.config.unit.width =  this.x;
		this.config.unit.height = this.y;
		this.config.floatConfig = this.floatConfig;
		this.config.dynamicSetup = this.dynamicSetup;
		this.config.videoType 	= this.videoType;
		this.config.playerDivSetup = {};
		this.config.url = this.url;
	}

	this._setReplaceUrlParam = function(paramName, newValue)
	{
		var regex = new RegExp("&"+paramName+"=[^&]+", "gm");
		this.url = this.url.replace(regex, '');
		regex = new RegExp("[?]"+paramName+"=[^&]+", "gm");
		this.url = this.url.replace(regex, '?');
		this.url += "&" + paramName + "=" +  newValue;
	}

	this._setObserverChecker = function()
	{
		try
		{
			if (this.debug)
			{
				console.log("SEKDBG: [INFO] browser="+this.ci.browser+", application="+this.isApp);
			}
			if (!this.isApp && !this.isAmpProject && !this.isAmpIframe &&
				((this.allowViewabilityCheck && (this.ci.browser == 'chrome' || this.ci.browser == 'edgeChromium')) || this.allowUserScrollCheck || this.lazyLoad))
			{
				this._setObserverElement();
				this._observerChecker();
			}
			else
			{
				this.allowViewabilityCheck = false;
				this.allowUserScrollCheck  = false;
			}
			if (this.debug)
			{
				console.log("SEKDBG: [INFO] viewable="+this.allowViewabilityCheck+", scroll="+this.allowUserScrollCheck+", lazyLoad="+this.lazyLoad);
			}
		}
		catch (e)
		{
			this.allowViewabilityCheck = false;
			this.allowUserScrollCheck  = false;
			this.lazyLoad = false;
			if (this.debug)
			{
				console.log("SEKDBG: [INFO] "+e.name + ": " + e.message);
			}
		}
	}

	this._observerChecker = function()
	{
		var observerOptions, currentScrollVerticalPosition=1, ref=this;
		if (ref.observerElement)
		{
			observerOptions = {
				root: null,
				rootMargin: '0px',
				threshold: [config.playerInViewPrc, config.adInViewPrc]
			}
			this.elementChecker = new ref.rootWindow.IntersectionObserver(intersectionCallback, observerOptions);
			this.elementChecker.observe(ref.observerElement);
		}
		if (ref.lazyLoad) {
			setTimeout(() => {
				ref.observedElementInfo.lazyLoadFinished = true;
				ref.process();
			}, ref.lazyLoad * 1000);
		}

		function intersectionCallback(entries, observer)
		{
			var intersectionEntry = entries[entries.length - 1];
			var currentViewedPercentage = intersectionEntry.intersectionRatio;
			ref.observedElementInfo.isViewable  = (currentViewedPercentage > ref.observedElementInfo.viewabilityThreshold);
			ref.observedElementInfo.hasScrolled = (currentViewedPercentage != currentScrollVerticalPosition);
			if (ref.debug)
			{
				console.log("SEKDBG: [INFO] percentage="+currentViewedPercentage+", in viewable="+ref.observedElementInfo.isViewable+", after scroll="+ref.observedElementInfo.hasScrolled);
			}
			currentScrollVerticalPosition = currentViewedPercentage;
			if ((ref.observedElementInfo.isViewable && ref.allowViewabilityCheck) || (ref.observedElementInfo.hasScrolled && ref.allowUserScrollCheck))
			{
				ref.elementChecker.unobserve(ref.observerElement);
				ref.process();
			}
		}
	}

	this._setObserverElement = function()
	{
		this.observerElement = null;
		if (this.allowUserScrollCheck)
		{
			var widgetElmt, mElmt, elmtId='extendedSection';
			mElmt = this.rootWindow.document.createElement('widget-markup');
			mElmt.setAttribute('id', elmtId);
			mElmt.setAttribute('style', 'width:0px; height:0px; position:absolute; top: 0px;');

			if (this.debug)
			{
				console.log("SEKDBG: [INFO] firstChild");
				console.log(this.rootWindow.document.body.firstChild);
			}
			this.rootWindow.document.body.insertBefore(mElmt, this.rootWindow.document.body.firstChild);
			widgetElmt = this.rootWindow.document.getElementById(elmtId);
			if (widgetElmt)
			{
				this.observerElement = widgetElmt;
			}
		}
		else if (typeof this.config.playerDivSetup.elmtClassName !== 'undefined' || typeof this.config.playerDivSetup.elmtId !== 'undefined' || typeof this.config.playerDivSetup.querySelector !== 'undefined')
		{
			this.observerElement = this.srcElement;
		}
		else if (this.srcElement && this.srcElement.parentNode)
		{
			if (this.frameInfo.isInsideGoogleFrame && typeof this.frameInfo.googleFrameId !== 'undefined')
			{
				this.observerElement = this.rootWindow.document.getElementById(this.frameInfo.googleFrameId);
			}
			else
			{
				this.observerElement = this.srcElement.parentNode;
			}
		}
		if (this.debug)
		{
			console.log("SEKDBG: [INFO] observer element");
			console.log(this.observerElement);
		}
		if (!this.observerElement)
		{
			this.allowViewabilityCheck = false;
			this.allowUserScrollCheck  = false;
		}
	}

	this._checkDebugInformationUrlParam = function(pageUrl)
	{
		var dbgInfo = new URL(pageUrl, location.href).searchParams.get("primisDebugInformation");
		if (dbgInfo) {
			this.url += '&debugInformation=' + dbgInfo;
			console.log("PRIMIS foreced debugInformation: " + dbgInfo);
		}
	}

	this._checkTemplateUrlParam = function(pageUrl)
	{
		var templateParam = new URL(pageUrl, location.href).searchParams.get("vp_template");
		if (templateParam) {
			this.url += '&vp_template=' + templateParam;
		}
	}

	this.playerApiActions = function(){
		function PrimisApiConfig (){
			this.setConfig = function (apiConfig){
				this.apiPlayerConfig = apiConfig;
			}
		}

		window.top.PrimisApiConfig = new PrimisApiConfig();
		window.top.dispatchEvent(new CustomEvent('readyConfigPlayerApi', {detail: window.top.PrimisApiConfig}));
	}

	this._setProb();
	this._setConfig();

	var dynamicConfig = new SekindoClientDynamicConfig(this.config, this.prob);
	dynamicConfig.run();
	// dynamicConfig can change this url
	this.url = this.config.url;

	this.getScriptElement();
	this.setInfo();
	if (this.isPlayerApiActions && !this.isAmpProject && !this.isAmpIframe && !this.isApp) this.playerApiActions();
	this.gdprConsentCheck = function () {
		return new Promise((resolve) => {
			var ref = this;
			ref.gdprResolve = resolve;
			this.isProcessFirstRun = false;

			this.gdprInfo.getIsWePass = function () {
				// Checks v2/v1 consent; returns true for isWePass if present, otherwise false.
				if (this.gdprInfo.v2 && this.gdprInfo.v2.consent) {
					return this.gdprInfo.v2.isWePass;
				} else {
					return this.gdprInfo.v1 && this.gdprInfo.v1.isWePass;
				}
			};

			this.gdprInfo.enableInframeTcfApi = function () {
				var t,a=window;var n={};for(;a;){try{if(a.frames.__tcfapiLocator){t=a;break}}catch(t){}if(a===window.top)break;a=a.parent}window.__tcfapi=function(a,e,c,o){if(t){var i=Math.random()+"",r={__tcfapiCall:{command:a,parameter:o,version:e,callId:i}};n[i]=c;try{t.postMessage(r,"*")}catch(err){c({msg:"postMessage failed"},!1)}}else c({msg:"CMP not found"},!1)},window.addEventListener("message",function(t){var a={};try{a="string"==typeof t.data?JSON.parse(t.data):t.data}catch(t){}var e=a.__tcfapiReturn;e&&"function"==typeof n[e.callId]&&(n[e.callId](e.returnValue,e.success),n[e.callId]=null)},!1);
			};

			this.gdprInfo.setTCF2ApiForIframeWindow = function (iframeWindow) {
				if (typeof window.__tcfapi === 'function') {
					iframeWindow.__tcfapi = window.__tcfapi;
				} else if (typeof window.top.__tcfapi === 'function') {
					iframeWindow.__tcfapi = window.top.__tcfapi;
				}
			};

			this.consentCallback = (gdprVersion, consent, isWePass) => {
				if (ref.consentCaptured) {
					if (ref.debug) {
						console.log("SEKDBG/GDPR: Skipping, consent already captured by GPP");
					}
					return;
				}

				const PRIMIS_VENDOR_ID = 228;
				let isGdprApproved = 0;
				if (isWePass == 'cmp1' || isWePass == 'tcf2') {
					switch (isWePass) {
						case 'cmp1': {
							const cmpHandler = new SekindoConsentHandler.ConsentString(consent);
							const vendorsAllowed = cmpHandler.getVendorsAllowed();
							isGdprApproved = (vendorsAllowed && vendorsAllowed.indexOf(PRIMIS_VENDOR_ID) !== -1 ? 1 : 0);
							break;
						}
						case 'tcf2': {
							try {
								const ptcStr = new Primis_TCString(consent);
								isGdprApproved = ptcStr.isVendorsAllowed([PRIMIS_VENDOR_ID]) ? 1 : 0;
							} catch (e) {
								if (ref.debug) {
									console.log("SEKDBG/GDPR: tcf2 error", e);
								}
							}
							break;
						}}
				} else {
					isGdprApproved = isWePass;
					switch (gdprVersion) {
						case 1: {
							ref.gdprInfo.v1.consent = consent;
							ref.gdprInfo.v1.isWePass = isGdprApproved ? 1 : 0;
							break;
						}
						case 2: {
							ref.gdprInfo.v2.consent = consent;
							ref.gdprInfo.v2.isWePass = isGdprApproved ? 1 : 0;
							break;
						}
					}
				}
				ref._finalizeConsent('gdpr', consent, isGdprApproved);
			};

			if (this.consentCaptured) {
				if (this.debug) {
					console.log("SEKDBG/GDPR: Skipping, consent already captured by GPP");
				}
				this.gdprResolve();
				return;
			}
			if (this.isAmpProject || this.isAmpIframe) {
				window.detectionAmpIframe(this.consentCallback);
			} else {
				this.gdprInfo.v1.handler = new SekindoClientDetections_GDPR(false, ref.gdprDetectionTimeout, function (consent, isWePass) {
					ref.consentCallback(1, consent, isWePass);
				}, false);

				this.gdprInfo.v2.handler = new SekindoClientDetections_GDPR_v2(false, ref.gdprDetectionTimeout, function (consent, isWePass) {
					ref.consentCallback(2, consent, isWePass);
				}, false);
			}
		});
	}

	if (config.gppDetectionTimeout !== undefined) {
		this.gppConsentCheck = function () {
			return new Promise((resolve) => {
				const ref = this;
				ref.gppResolve = resolve;
				this.isGppProcessFirstRun = false;
				this.gppConsentCallback = function (gppString, gppResult) {
					if (ref.consentCaptured) {
						if (ref.debug) {
							console.log("SEKDBG/GPP: Skipping, consent already captured by GDPR");
						}
						return;
					}

					if (ref.debug) {
						console.log("SEKDBG/GPP: Consent callback received");
						console.log("SEKDBG/GPP: String: " + gppString);
						console.log("SEKDBG/GPP: Result: ", gppResult);
					}

					ref.gppInfo.consent = gppString || '';

					if (gppResult) {
						if (gppResult.ccpaConsentString) {
							ref.gppInfo.ccpa.consent = gppResult.ccpaConsentString;
							ref.gppInfo.ccpa.isRejected = gppResult.ccpa ? 0 : 1;
							ref.url += '&ccpaConsent=' + encodeURIComponent(ref.gppInfo.ccpa.consent);
						}
						if (ref.gppInfo.consent && ref.gppInfo.consent.length > 0) {
							ref.url += '&gppConsent=' + encodeURIComponent(ref.gppInfo.consent);
						}
						if (gppResult.gppSid) {
							ref.gppInfo.sid = gppResult.gppSid;
							ref.url += '&gppSid=' + encodeURIComponent(gppResult.gppSid);
						}
						if (gppResult.gdprConsentString) {
							ref.gppInfo.gdpr.consent = gppResult.gdprConsentString;
							ref.gppInfo.gdpr.isWePass = gppResult.gdpr ? 1 : 0;
						}
					}
					ref._finalizeConsent('gpp', ref.gppInfo.gdpr.consent, ref.gppInfo.gdpr.isWePass);
				};

				if (this.consentCaptured) {
					if (this.debug) {
						console.log("SEKDBG/GPP: Skipping, consent already captured by GDPR");
					}
					this.gppResolve();
					return;
				}
				if (!this.isAmpProject && !this.isAmpIframe) {
					try {
						this.gppInfo.handler = new SekindoClientDetections_GPP(this.debug, this.gppDetectionTimeout, this.gppConsentCallback, this.isApp, this.isEnableGDPRListener);
					} catch (e) {
						if (this.debug) {
							console.log("SEKDBG/GPP: Failed to initialize GPP handler", e);
						}
						this.gppResolve();
					}
				} else {
					if (this.debug) {
						console.log("SEKDBG/GPP: SekindoClientDetections_GPP not available or AMP context");
					}
					this.gppResolve();
				}
			});
		};
	}

	this._finalizeConsent = function(type, consent, isGdprApproved) {
		if (this.consentCaptured) {
			return;
		}
		if (type == 'gdpr') {
			if (consent) {
				this.consentCaptured = true;
				if (this.isEnableGPPListener && typeof this.gppResolve === 'function') {
					if (this.debug) {
						console.log("GPP short-circuited via GDPR callback");
					}
					this.gppResolve();
				}
				this.url += (isGdprApproved ? '&isWePassGdpr=1' : '&isWePassGdpr=0') + '&gdprConsent=' + consent;
				if (!this.gppInfo.consent && !this.gppInfo.sid) {
					this.url += '&gppConsent=&gppSid=';
				}
				if (isGdprApproved) {
					this._getUuid();
				}
			}
			this.gdprResolve();
		} else if (type == 'gpp') {
			if (consent) {
				this.consentCaptured = true;
				if (this.isEnableGDPRListener && typeof this.gdprResolve === 'function') {
					if (this.debug) {
						console.log("GDPR short-circuited via GPP callback");
					}
					this.gdprResolve();
				}
				this.url += '&gdprConsent=' + consent + '&isWePassGdpr=' + isGdprApproved;
				if (isGdprApproved) {
					this._getUuid();
				}
			}
			this.gppResolve();
		}
	}
};

				var urlDetObj = new SekindoClientDetections_URL({
					url: 'https://live.primis.tech/live/liveView.php?s=119799&schain=1.0,1!publift.com,01JP6NKKZ2Y0TRBZNB6K8EWR0C,1&cbuster=1787815731',
					origQString: 's=119799&schain=1.0,1!publift.com,01JP6NKKZ2Y0TRBZNB6K8EWR0C,1',
					placementId: 119799,
					x: 300,
					y: 250,
					videoType: 'flow',
					needWrappingIframe: 1,
					isAmpProject: 0,
					isAmpIframe: 0,
					floatConfig: {
						width: '', height: '',
						direction: '', verticalOffset: '',
						horizontalOffset: '', isCloseBtn: '',
						flowMode: '', closeBtnPos: ''
					},
					isAPI: false,
					debug: 0,
					ci: {"extra":{"schemaVer":"11","os":"Linux","osVersion":"","osVersionMajor":"0","osVersionMinor":"0","deviceManufacturer":"","deviceModel":"","deviceCodeName":"","deviceType":"desktop","browser":"Chrome","browserType":"browser","browserVersion":"151.0.0.0","browserVersionMajor":"151","browserVersionMinor":"0","chromeVersion":"151"},"browser":"chrome","os":"other","osVer":"","deviceType":"desktop","languages":["en"],"googlePSI":false},
					isFpCookie: 0,
					geo: 'GB',
					dmaCode: 0,
					dynamicSetup: [],
					uuid: '6a8fe733c7b0e',
					isResponsiveBanner: false,
					hideOnMissingMainElement: false,
					allowedUtmParameters: [],
					allowDisplaySamePlacementAgain: true,
					blockOtherPlacements: false,
					searchMetaTagNames: {"tagAttribute":"property","tagName":"og:category"},
					customTargetingProperties: false,
					customPpidMapping: false,
					sharedVideoParameterName: 'primis_content',
					gamTargetingVideoParameterName: 'primis_custom_target',
                    placementType: 'slBanner',
					isApp: false,
					playerInViewPrc: 0.01,
					adInViewPrc: 0.5,
					allowViewabilityCheck: false,
					allowUserScrollCheck: false,
                    lazyLoad: false,
					isRun: 1,
					isPlayerApiActions: false,
					gdprDetectionTimeout: 60000,
					isEnableGDPRListener: true,
					isEnableGPPListener: true,
					gppDetectionTimeout: 60000				});
				urlDetObj.process();
			})();
			