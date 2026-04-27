/* ═══════════════════════════════════════════════════════════════
   QR / NFC Generator — portal integration
   Namespace: window.QRG
   All DOM IDs prefixed "qrg-" to avoid collisions with portal.
   QR library: Kazuhiko Arase (MIT) — inline, no CDN needed.
   ═══════════════════════════════════════════════════════════════ */

/* ── Kazuhiko Arase qrcode-generator (MIT) ─────────────────── */
var qrcode = function() {
  var QRErrorCorrectionLevel = { L: 1, M: 0, Q: 3, H: 2 };
  var QRMath = {
    glog: function(n) { if (n < 1) throw new Error('glog(' + n + ')'); return QRMath.LOG_TABLE[n]; },
    gexp: function(n) { while (n < 0) n += 255; while (n >= 256) n -= 255; return QRMath.EXP_TABLE[n]; },
    EXP_TABLE: (function(){ var t=new Array(256),i; for(i=0;i<8;i++) t[i]=1<<i; for(i=8;i<256;i++) t[i]=t[i-4]^t[i-5]^t[i-6]^t[i-8]; return t; })(),
    LOG_TABLE: (function(){ var t=new Array(256); for(var i=0;i<255;i++) t[1<<(i%255)%256|0]=i; /* simple placeholder */
      /* proper init */ var EXP=new Array(256),i; for(i=0;i<8;i++) EXP[i]=1<<i; for(i=8;i<256;i++) EXP[i]=EXP[i-4]^EXP[i-5]^EXP[i-6]^EXP[i-8];
      var LOG=new Array(256); for(i=0;i<255;i++) LOG[EXP[i]]=i; LOG[0]=0; return LOG; })()
  };
  // NOTE: The above is an abbreviated placeholder. The real library is inlined below via IIFE.
  return null; // replaced by full IIFE below
}; qrcode = null; // reset — full library follows

// ── Full Kazuhiko Arase qrcode-generator (MIT) ───────────────
/* eslint-disable */
var qrcode = function() {

  var QRErrorCorrectionLevel = { L : 1, M : 0, Q : 3, H : 2 };

  var QRMath = function() {
    var EXP_TABLE = new Array(256);
    var LOG_TABLE = new Array(256);
    for (var i = 0; i < 8; i += 1) { EXP_TABLE[i] = 1 << i; }
    for (var i = 8; i < 256; i += 1) { EXP_TABLE[i] = EXP_TABLE[i - 4] ^ EXP_TABLE[i - 5] ^ EXP_TABLE[i - 6] ^ EXP_TABLE[i - 8]; }
    for (var i = 0; i < 255; i += 1) { LOG_TABLE[EXP_TABLE[i]] = i; }
    return {
      glog: function(n) { if (n < 1) throw new Error('glog(' + n + ')'); return LOG_TABLE[n]; },
      gexp: function(n) { while (n < 0) n += 255; while (n >= 256) n -= 255; return EXP_TABLE[n]; }
    };
  }();

  var qrPolynomial = function(num, shift) {
    if (typeof num.length == 'undefined') throw new Error(num.length + '/' + shift);
    var _num = function() { var i = 0; while (i < num.length && num[i] == 0) i += 1; var n = new Array(num.length - i + shift); for (var j = 0; j < num.length - i; j += 1) n[j] = num[j + i]; return n; }();
    var _this = {
      getAt: function(index) { return _num[index]; },
      getLength: function() { return _num.length; },
      multiply: function(e) { var n = new Array(_this.getLength() + e.getLength() - 1); for (var i = 0; i < _this.getLength(); i += 1) for (var j = 0; j < e.getLength(); j += 1) n[i + j] ^= QRMath.gexp(QRMath.glog(_this.getAt(i)) + QRMath.glog(e.getAt(j))); return qrPolynomial(n, 0); },
      mod: function(e) { if (_this.getLength() - e.getLength() < 0) return _this; var ratio = QRMath.glog(_this.getAt(0)) - QRMath.glog(e.getAt(0)); var n = new Array(_this.getLength()); for (var i = 0; i < _this.getLength(); i += 1) n[i] = _this.getAt(i); for (var i = 0; i < e.getLength(); i += 1) n[i] ^= QRMath.gexp(QRMath.glog(e.getAt(i)) + ratio); return qrPolynomial(n, 0).mod(e); }
    }; return _this;
  };

  var QRUtil = function() {
    var PATTERN_POSITION_TABLE = [[],[6,18],[6,22],[6,26],[6,30],[6,34],[6,22,38],[6,24,42],[6,26,46],[6,28,50],[6,30,54],[6,32,58],[6,34,62],[6,26,46,66],[6,26,48,70],[6,26,50,74],[6,30,54,78],[6,30,56,82],[6,30,58,86],[6,34,62,90],[6,28,50,72,94],[6,26,50,74,98],[6,30,54,78,102],[6,28,54,80,106],[6,32,58,84,110],[6,30,58,86,114],[6,34,62,90,118],[6,26,50,74,98,122],[6,30,54,78,102,126],[6,26,52,78,104,130],[6,30,56,82,108,134],[6,34,60,86,112,138],[6,30,58,86,114,142],[6,34,62,90,118,146],[6,30,54,78,102,126,150],[6,24,50,76,102,128,154],[6,28,54,80,106,132,158],[6,32,58,84,110,136,162],[6,26,54,82,110,138,166],[6,30,58,86,114,142,170]];
    var G15 = (1 << 10) | (1 << 8) | (1 << 5) | (1 << 4) | (1 << 2) | (1 << 1) | (1 << 0);
    var G18 = (1 << 12) | (1 << 11) | (1 << 10) | (1 << 9) | (1 << 8) | (1 << 5) | (1 << 2) | (1 << 0);
    var G15_MASK = (1 << 14) | (1 << 12) | (1 << 10) | (1 << 4) | (1 << 1);
    var _this = {
      getBCHTypeInfo: function(data) { var d = data << 10; while (_this.getBCHDigit(d) - _this.getBCHDigit(G15) >= 0) d ^= (G15 << (_this.getBCHDigit(d) - _this.getBCHDigit(G15))); return ( (data << 10) | d) ^ G15_MASK; },
      getBCHTypeNumber: function(data) { var d = data << 12; while (_this.getBCHDigit(d) - _this.getBCHDigit(G18) >= 0) d ^= (G18 << (_this.getBCHDigit(d) - _this.getBCHDigit(G18))); return (data << 12) | d; },
      getBCHDigit: function(data) { var d = 0; while (data != 0) { d += 1; data >>>= 1; } return d; },
      getPatternPosition: function(typeNumber) { return PATTERN_POSITION_TABLE[typeNumber - 1]; },
      getMaskFunction: function(maskPattern) {
        switch (maskPattern) {
          case 0: return function(i,j){ return (i+j)%2==0; };
          case 1: return function(i,j){ return i%2==0; };
          case 2: return function(i,j){ return j%3==0; };
          case 3: return function(i,j){ return (i+j)%3==0; };
          case 4: return function(i,j){ return (Math.floor(i/2)+Math.floor(j/3))%2==0; };
          case 5: return function(i,j){ return (i*j)%2+(i*j)%3==0; };
          case 6: return function(i,j){ return ((i*j)%2+(i*j)%3)%2==0; };
          case 7: return function(i,j){ return ((i*j)%3+(i+j)%2)%2==0; };
          default: throw new Error('bad maskPattern:' + maskPattern);
        }
      },
      getErrorCorrectPolynomial: function(errorCorrectLength) { var a = qrPolynomial([1], 0); for (var i = 0; i < errorCorrectLength; i += 1) a = a.multiply(qrPolynomial([1, QRMath.gexp(i)], 0)); return a; },
      getLostPoint: function(qrcode) {
        var mc = qrcode.getModuleCount(), lp = 0;
        for (var r = 0; r < mc; r += 1) for (var c = 0; c < mc; c += 1) {
          var s = 0, d = qrcode.isDark(r, c);
          for (var dr = -1; dr <= 1; dr += 1) for (var dc = -1; dc <= 1; dc += 1) {
            if (r+dr<0||mc<=r+dr||c+dc<0||mc<=c+dc) continue;
            if (dr==0&&dc==0) continue;
            if (d==qrcode.isDark(r+dr,c+dc)) s+=1;
          }
          if (s>5) lp+=(3+s-5);
        }
        for (var r = 0; r < mc-1; r+=1) for (var c = 0; c < mc-1; c+=1) {
          var ct=0; if(qrcode.isDark(r,c))ct+=1; if(qrcode.isDark(r+1,c))ct+=1; if(qrcode.isDark(r,c+1))ct+=1; if(qrcode.isDark(r+1,c+1))ct+=1;
          if(ct==0||ct==4) lp+=3;
        }
        for (var r = 0; r < mc; r+=1) for (var c = 0; c < mc-6; c+=1) {
          if(qrcode.isDark(r,c)&&!qrcode.isDark(r,c+1)&&qrcode.isDark(r,c+2)&&qrcode.isDark(r,c+3)&&qrcode.isDark(r,c+4)&&!qrcode.isDark(r,c+5)&&qrcode.isDark(r,c+6))lp+=40;
        }
        for (var c = 0; c < mc; c+=1) for (var r = 0; r < mc-6; r+=1) {
          if(qrcode.isDark(r,c)&&!qrcode.isDark(r+1,c)&&qrcode.isDark(r+2,c)&&qrcode.isDark(r+3,c)&&qrcode.isDark(r+4,c)&&!qrcode.isDark(r+5,c)&&qrcode.isDark(r+6,c))lp+=40;
        }
        var dk=0; for(var r=0;r<mc;r+=1)for(var c=0;c<mc;c+=1)if(qrcode.isDark(r,c))dk+=1;
        var ratio=Math.abs(100*dk/mc/mc-50)/5; lp+=ratio*10;
        return lp;
      }
    }; return _this;
  }();

  var QRRSBlock = function() {
    var RS_BLOCK_TABLE = [[1,26,19],[1,26,16],[1,26,13],[1,26,9],[1,44,34],[1,44,28],[1,44,22],[1,44,16],[1,70,55],[1,70,44],[2,35,17],[2,35,13],[1,100,80],[2,50,32],[2,50,24],[4,25,9],[1,134,108],[2,67,43],[2,33,15,2,34,16],[2,33,11,2,34,12],[2,86,68],[4,43,27],[4,43,19],[4,43,15],[2,98,78],[4,49,31],[2,32,14,4,33,15],[4,39,13,1,40,14],[2,121,97],[2,60,38,2,61,39],[4,40,18,2,41,19],[4,40,14,2,41,15],[2,146,116],[3,58,36,2,59,37],[4,36,16,4,37,17],[4,36,12,4,37,13],[2,86,68,2,87,69],[4,69,43,1,70,44],[6,43,19,2,44,20],[6,43,15,2,44,16],[4,101,81],[1,80,50,4,81,51],[4,50,22,4,51,23],[3,36,12,8,37,13],[2,116,92,2,117,93],[6,58,36,2,59,37],[4,46,20,6,47,21],[7,42,14,4,43,15],[4,133,107],[8,59,37,1,60,38],[8,44,20,4,45,21],[12,33,11,4,34,12],[3,145,115,1,146,116],[4,64,40,5,65,41],[11,36,16,5,37,17],[11,36,12,5,37,13],[5,109,87,1,110,88],[5,65,41,5,66,42],[5,54,24,7,55,25],[11,36,12],[5,122,98,1,123,99],[7,73,45,3,74,46],[15,43,19,2,44,20],[3,45,15,13,46,16],[1,135,107,5,136,108],[10,74,46,1,75,47],[1,50,22,15,51,23],[2,42,14,17,43,15],[5,150,120,1,151,121],[9,69,43,4,70,44],[17,50,22,1,51,23],[2,42,14,19,43,15],[3,141,113,4,142,114],[3,70,44,11,71,45],[17,47,21,4,48,22],[9,39,13,16,40,14],[3,135,107,5,136,108],[3,67,41,13,68,42],[15,54,24,5,55,25],[15,43,15,10,44,16],[4,144,116,4,145,117],[17,68,42],[17,50,22,6,51,23],[19,46,16,6,47,17],[2,139,111,7,140,112],[17,74,46],[7,54,24,16,55,25],[34,37,13],[4,151,121,5,152,122],[4,75,47,14,76,48],[11,54,24,14,55,25],[16,45,15,14,46,16],[6,147,117,4,148,118],[6,73,45,14,74,46],[11,54,24,16,55,25],[30,46,16,2,47,17],[8,132,106,4,133,107],[8,75,47,13,76,48],[7,54,24,22,55,25],[22,45,15,13,46,16],[10,142,114,2,143,115],[19,74,46,4,75,47],[28,50,22,6,51,23],[33,46,16,4,47,17],[8,152,122,4,153,123],[22,73,45,3,74,46],[8,53,23,26,54,24],[12,45,15,28,46,16],[3,147,117,10,148,118],[3,73,45,23,74,46],[4,54,24,31,55,25],[11,45,15,31,46,16],[7,146,116,7,147,117],[21,73,45,7,74,46],[1,53,23,37,54,24],[19,45,15,26,46,16],[5,145,115,10,146,116],[19,75,47,10,76,48],[15,54,24,25,55,25],[23,45,15,25,46,16],[13,145,115,3,146,116],[2,74,46,29,75,47],[42,54,24,1,55,25],[23,45,15,28,46,16],[17,145,115],[10,74,46,23,75,47],[10,54,24,35,55,25],[19,45,15,35,46,16],[17,145,115,1,146,116],[14,74,46,21,75,47],[29,54,24,19,55,25],[11,45,15,46,46,16],[13,145,115,6,146,116],[14,74,46,23,75,47],[44,54,24,7,55,25],[59,46,16,1,47,17],[12,151,121,7,152,122],[12,75,47,26,76,48],[39,54,24,14,55,25],[22,45,15,41,46,16],[6,151,121,14,152,122],[6,75,47,34,76,48],[46,54,24,10,55,25],[2,45,15,64,46,16],[17,152,122,4,153,123],[29,74,46,14,75,47],[49,54,24,10,55,25],[24,45,15,46,46,16],[4,152,122,18,153,123],[13,74,46,32,75,47],[48,54,24,14,55,25],[42,45,15,32,46,16],[20,147,117,4,148,118],[40,75,47,7,76,48],[43,54,24,22,55,25],[10,45,15,67,46,16],[19,148,118,6,149,119],[18,75,47,31,76,48],[34,54,24,34,55,25],[20,45,15,61,46,16]];
    var _this = {
      getRSBlocks: function(typeNumber, errorCorrectionLevel) {
        var rsBlock = _this.getRsBlockTable(typeNumber, errorCorrectionLevel);
        if (typeof rsBlock == 'undefined') throw new Error('bad rs block @ typeNumber:' + typeNumber + '/errorCorrectionLevel:' + errorCorrectionLevel);
        var length = rsBlock.length / 3, list = [];
        for (var i = 0; i < length; i += 1) { var count=rsBlock[i*3+0],totalCount=rsBlock[i*3+1],dataCount=rsBlock[i*3+2]; for(var j=0;j<count;j+=1) list.push({totalCount:totalCount,dataCount:dataCount}); }
        return list;
      },
      getRsBlockTable: function(typeNumber, errorCorrectionLevel) {
        switch(errorCorrectionLevel){case QRErrorCorrectionLevel.L:return RS_BLOCK_TABLE[(typeNumber-1)*4+0];case QRErrorCorrectionLevel.M:return RS_BLOCK_TABLE[(typeNumber-1)*4+1];case QRErrorCorrectionLevel.Q:return RS_BLOCK_TABLE[(typeNumber-1)*4+2];case QRErrorCorrectionLevel.H:return RS_BLOCK_TABLE[(typeNumber-1)*4+3];default:return undefined;}
      }
    }; return _this;
  }();

  var qrBitBuffer = function() {
    var _buffer = [], _length = 0;
    return {
      getBuffer: function(){ return _buffer; },
      getAt: function(index){ var bufIndex=Math.floor(index/8); return ((_buffer[bufIndex]>>>(7-index%8))&1)==1; },
      put: function(num,length){ for(var i=0;i<length;i+=1) this.putBit(((num>>>(length-i-1))&1)==1); },
      getLengthInBits: function(){ return _length; },
      putBit: function(bit){ var bufIndex=Math.floor(_length/8); if(_buffer.length<=bufIndex)_buffer.push(0); if(bit)_buffer[bufIndex]|=(0x80>>>(_length%8)); _length+=1; }
    };
  };

  var qrcode = function(typeNumber, errorCorrectionLevel) {
    var PAD0=0xEC, PAD1=0x11;
    var _typeNumber=typeNumber;
    var _errorCorrectionLevel=QRErrorCorrectionLevel[errorCorrectionLevel];
    var _modules=null, _moduleCount=0, _dataCache=null, _dataList=[];
    var _this = {};

    var makeImpl=function(test,maskPattern){
      _moduleCount=_typeNumber*4+17;
      _modules=(function(mc){var m=new Array(mc);for(var r=0;r<mc;r++){m[r]=new Array(mc);for(var c=0;c<mc;c++)m[r][c]=null;}return m;})(_moduleCount);
      setupPositionProbePattern(0,0); setupPositionProbePattern(_moduleCount-7,0); setupPositionProbePattern(0,_moduleCount-7);
      setupPositionAdjustPattern(); setupTimingPattern(); setupTypeInfo(test,maskPattern);
      if(_typeNumber>=7)setupTypeNumber(test);
      if(_dataCache==null)_dataCache=createData(_typeNumber,_errorCorrectionLevel,_dataList);
      mapData(_dataCache,maskPattern);
    };
    var setupPositionProbePattern=function(row,col){for(var r=-1;r<=7;r++){if(row+r<=-1||_moduleCount<=row+r)continue;for(var c=-1;c<=7;c++){if(col+c<=-1||_moduleCount<=col+c)continue;_modules[row+r][col+c]=((0<=r&&r<=6&&(c==0||c==6))||(0<=c&&c<=6&&(r==0||r==6))||(2<=r&&r<=4&&2<=c&&c<=4));}}};
    var getBestMaskPattern=function(){var min=0,pat=0;for(var i=0;i<8;i++){makeImpl(true,i);var lp=QRUtil.getLostPoint(_this);if(i==0||min>lp){min=lp;pat=i;}}return pat;};
    var setupTimingPattern=function(){for(var r=8;r<_moduleCount-8;r++)if(_modules[r][6]==null)_modules[r][6]=(r%2==0);for(var c=8;c<_moduleCount-8;c++)if(_modules[6][c]==null)_modules[6][c]=(c%2==0);};
    var setupPositionAdjustPattern=function(){var pos=QRUtil.getPatternPosition(_typeNumber);for(var i=0;i<pos.length;i++)for(var j=0;j<pos.length;j++){var row=pos[i],col=pos[j];if(_modules[row][col]!=null)continue;for(var r=-2;r<=2;r++)for(var c=-2;c<=2;c++)_modules[row+r][col+c]=(r==-2||r==2||c==-2||c==2||(r==0&&c==0));}};
    var setupTypeNumber=function(test){var bits=QRUtil.getBCHTypeNumber(_typeNumber);for(var i=0;i<18;i++){var mod=(!test&&((bits>>i)&1)==1);_modules[Math.floor(i/3)][i%3+_moduleCount-8-3]=mod;}for(var i=0;i<18;i++){var mod=(!test&&((bits>>i)&1)==1);_modules[i%3+_moduleCount-8-3][Math.floor(i/3)]=mod;}};
    var setupTypeInfo=function(test,maskPattern){var data=(_errorCorrectionLevel<<3)|maskPattern,bits=QRUtil.getBCHTypeInfo(data);for(var i=0;i<15;i++){var mod=(!test&&((bits>>i)&1)==1);if(i<6)_modules[i][8]=mod;else if(i<8)_modules[i+1][8]=mod;else _modules[_moduleCount-15+i][8]=mod;}for(var i=0;i<15;i++){var mod=(!test&&((bits>>i)&1)==1);if(i<8)_modules[8][_moduleCount-i-1]=mod;else if(i<9)_modules[8][15-i-1+1]=mod;else _modules[8][15-i-1]=mod;}_modules[_moduleCount-8][8]=(!test);};
    var mapData=function(data,maskPattern){var inc=-1,row=_moduleCount-1,bitIndex=7,byteIndex=0,maskFunc=QRUtil.getMaskFunction(maskPattern);for(var col=_moduleCount-1;col>0;col-=2){if(col==6)col-=1;while(true){for(var c=0;c<2;c++){if(_modules[row][col-c]==null){var dark=false;if(byteIndex<data.length)dark=((data[byteIndex]>>>bitIndex)&1)==1;if(maskFunc(row,col-c))dark=!dark;_modules[row][col-c]=dark;bitIndex-=1;if(bitIndex==-1){byteIndex+=1;bitIndex=7;}}}row+=inc;if(row<0||_moduleCount<=row){row-=inc;inc=-inc;break;}}}};
    var createBytes=function(buffer,rsBlocks){var offset=0,maxDc=0,maxEc=0,dcdata=new Array(rsBlocks.length),ecdata=new Array(rsBlocks.length);for(var r=0;r<rsBlocks.length;r++){var dcCount=rsBlocks[r].dataCount,ecCount=rsBlocks[r].totalCount-dcCount;maxDc=Math.max(maxDc,dcCount);maxEc=Math.max(maxEc,ecCount);dcdata[r]=new Array(dcCount);for(var i=0;i<dcdata[r].length;i++)dcdata[r][i]=0xff&buffer.getBuffer()[i+offset];offset+=dcCount;var rsPoly=QRUtil.getErrorCorrectPolynomial(ecCount),rawPoly=qrPolynomial(dcdata[r],rsPoly.getLength()-1),modPoly=rawPoly.mod(rsPoly);ecdata[r]=new Array(rsPoly.getLength()-1);for(var i=0;i<ecdata[r].length;i++){var modIndex=i+modPoly.getLength()-ecdata[r].length;ecdata[r][i]=(modIndex>=0)?modPoly.getAt(modIndex):0;}}var totalCodeCount=0;for(var i=0;i<rsBlocks.length;i++)totalCodeCount+=rsBlocks[i].totalCount;var data=new Array(totalCodeCount),index=0;for(var i=0;i<maxDc;i++)for(var r=0;r<rsBlocks.length;r++)if(i<dcdata[r].length){data[index]=dcdata[r][i];index++;}for(var i=0;i<maxEc;i++)for(var r=0;r<rsBlocks.length;r++)if(i<ecdata[r].length){data[index]=ecdata[r][i];index++;}return data;};
    var createData=function(typeNumber,errorCorrectionLevel,dataList){var rsBlocks=QRRSBlock.getRSBlocks(typeNumber,errorCorrectionLevel),buffer=qrBitBuffer();for(var i=0;i<dataList.length;i++){var data=dataList[i];buffer.put(data.getMode(),4);buffer.put(data.getLength(),QRMode.getLengthInBits(data.getMode(),typeNumber));data.write(buffer);}var totalDataCount=0;for(var i=0;i<rsBlocks.length;i++)totalDataCount+=rsBlocks[i].dataCount;if(buffer.getLengthInBits()>totalDataCount*8)throw new Error('code length overflow. ('+buffer.getLengthInBits()+'>'+totalDataCount*8+')');if(buffer.getLengthInBits()+4<=totalDataCount*8)buffer.put(0,4);while(buffer.getLengthInBits()%8!=0)buffer.putBit(false);while(true){if(buffer.getLengthInBits()>=totalDataCount*8)break;buffer.put(PAD0,8);if(buffer.getLengthInBits()>=totalDataCount*8)break;buffer.put(PAD1,8);}return createBytes(buffer,rsBlocks);};

    _this.addData=function(data,mode){mode=mode||'Byte';var newData;switch(mode){case 'Numeric':newData=qrNumber(data);break;case 'Alphanumeric':newData=qrAlphaNum(data);break;case 'Byte':newData=qr8BitByte(data);break;case 'Kanji':newData=qrKanji(data);break;default:throw new Error('mode:'+mode);}; _dataList.push(newData);_dataCache=null;};
    _this.isDark=function(row,col){if(row<0||_moduleCount<=row||col<0||_moduleCount<=col)throw new Error(row+','+col);return _modules[row][col];};
    _this.getModuleCount=function(){return _moduleCount;};
    _this.make=function(){if(_typeNumber<1){for(var typeNumber=1;typeNumber<40;typeNumber++){var rsBlocks=QRRSBlock.getRSBlocks(typeNumber,_errorCorrectionLevel),buffer=qrBitBuffer();for(var i=0;i<_dataList.length;i++){var data=_dataList[i];buffer.put(data.getMode(),4);buffer.put(data.getLength(),QRMode.getLengthInBits(data.getMode(),typeNumber));data.write(buffer);}if(buffer.getLengthInBits()<=QRRSBlock.getRSBlocks(typeNumber,_errorCorrectionLevel).reduce(function(a,b){return a+b.dataCount;},0)*8){_typeNumber=typeNumber;break;}}}_errorCorrectionLevel=QRErrorCorrectionLevel[_errorCorrectionLevel]!==undefined?_errorCorrectionLevel:_errorCorrectionLevel;makeImpl(false,getBestMaskPattern());};
    return _this;
  };

  var QRMode = {
    MODE_NUMBER: 1<<0, MODE_ALPHA_NUM: 1<<1, MODE_8BIT_BYTE: 1<<2, MODE_KANJI: 1<<3,
    getLengthInBits: function(mode, type) {
      if(type>=1&&type<10){switch(mode){case QRMode.MODE_NUMBER:return 10;case QRMode.MODE_ALPHA_NUM:return 9;case QRMode.MODE_8BIT_BYTE:return 8;case QRMode.MODE_KANJI:return 8;default:throw new Error('mode:'+mode);}}
      else if(type<27){switch(mode){case QRMode.MODE_NUMBER:return 12;case QRMode.MODE_ALPHA_NUM:return 11;case QRMode.MODE_8BIT_BYTE:return 16;case QRMode.MODE_KANJI:return 10;default:throw new Error('mode:'+mode);}}
      else{switch(mode){case QRMode.MODE_NUMBER:return 14;case QRMode.MODE_ALPHA_NUM:return 13;case QRMode.MODE_8BIT_BYTE:return 16;case QRMode.MODE_KANJI:return 12;default:throw new Error('mode:'+mode);}}
    }
  };

  var qr8BitByte = function(data) {
    var _mode=QRMode.MODE_8BIT_BYTE, _bytes=[];
    try{var enc=new TextEncoder();_bytes=Array.from(enc.encode(data));}catch(e){for(var i=0;i<data.length;i++){var c=data.charCodeAt(i);if(c<128)_bytes.push(c);else if(c<2048){_bytes.push(0xC0|(c>>6));_bytes.push(0x80|(c&0x3F));}else{_bytes.push(0xE0|(c>>12));_bytes.push(0x80|((c>>6)&0x3F));_bytes.push(0x80|(c&0x3F));}}}
    return { getMode:function(){return _mode;}, getLength:function(){return _bytes.length;}, write:function(buffer){for(var i=0;i<_bytes.length;i++)buffer.put(_bytes[i],8);} };
  };
  var qrNumber = function(data) {
    var _mode=QRMode.MODE_NUMBER,_data=data;
    return { getMode:function(){return _mode;}, getLength:function(){return _data.length;}, write:function(buffer){var i=0;while(i+2<_data.length){buffer.put(parseInt(_data.substring(i,i+3),10),10);i+=3;}if(i+1<_data.length){buffer.put(parseInt(_data.substring(i,i+2),10),7);i+=2;}else if(i<_data.length){buffer.put(parseInt(_data.substring(i,i+1),10),4);}} };
  };
  var qrAlphaNum = function(data) {
    var _mode=QRMode.MODE_ALPHA_NUM,_data=data;
    var CHARS='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:';
    return { getMode:function(){return _mode;}, getLength:function(){return _data.length;}, write:function(buffer){var i=0;while(i+1<_data.length){buffer.put(CHARS.indexOf(_data[i])*45+CHARS.indexOf(_data[i+1]),11);i+=2;}if(i<_data.length)buffer.put(CHARS.indexOf(_data[i]),6);} };
  };
  var qrKanji = function(data) {
    var _mode=QRMode.MODE_KANJI,_bytes=[];
    for(var i=0;i<data.length;i++){var c=data.charCodeAt(i);var code=(c>=0x8140&&c<=0x9FFC)?c-0x8140:(c>=0xE040&&c<=0xEBBF)?c-0xC140:0;_bytes.push((code>>8)&0xFF,code&0xFF);}
    return { getMode:function(){return _mode;}, getLength:function(){return _bytes.length/2;}, write:function(buffer){for(var i=0;i<_bytes.length;i+=2){buffer.put(((_bytes[i]<<8)|_bytes[i+1]),13);}} };
  };

  return qrcode;
}();
/* eslint-enable */

/* ══════════════════════════════════════════════════════════════
   QRG — Application Namespace
   ══════════════════════════════════════════════════════════════ */
window.QRG = (function() {
  'use strict';

  // ── State ──────────────────────────────────────────────────
  var mode        = 'url';
  var iconData    = null;
  var activeFrame = 'none';
  var activeIconId = null;
  var iconSource  = 'preset';
  var _idCounter  = 0;
  var _currentQId = '';
  var _currentNId = '';
  var gtimer      = null;

  // ── Helper: scoped getElementById ──────────────────────────
  function el(id) { return document.getElementById(id); }

  // ── ID generator ───────────────────────────────────────────
  function generateId(type) {
    var timePart    = String(Date.now()).slice(-6);
    _idCounter = (_idCounter + 1) % 1000;
    var counterPart = String(_idCounter).padStart(3, '0');
    var randomPart  = String(Math.floor(Math.random() * 100)).padStart(2, '0');
    return 'HPS' + type + timePart + counterPart + randomPart;
  }

  function regenerateId(type) {
    var id = generateId(type);
    if (type === 'Q') {
      _currentQId = id;
      var e = el('qrg-url-generated-id'); if (e) e.textContent = id;
    } else {
      _currentNId = id;
      var e = el('qrg-nfc-generated-id'); if (e) e.textContent = id;
      var d = el('qrg-nfc-url-display'); if (d) d.textContent = 'https://pinplot.me/asset/' + id;
    }
    generate();
  }

  // ── Mode switching ─────────────────────────────────────────
  function setMode(m) {
    mode = m;
    var isNfc = m === 'nfc';
    el('qrg-mode-url').style.display  = m === 'url'  ? '' : 'none';
    el('qrg-mode-nfc').style.display  = m === 'nfc'  ? '' : 'none';
    el('qrg-mode-imei').style.display = m === 'imei' ? '' : 'none';
    document.querySelectorAll('#qr-root .qrg-tab').forEach(function(t) {
      var tid = t.dataset.mode;
      t.classList.toggle('active', tid === m);
    });
    el('qrg-preview-wrap').style.display         = isNfc ? 'none' : '';
    el('qrg-nfc-placeholder-wrap').style.display = isNfc ? '' : 'none';
    el('qrg-dl-buttons').style.display            = isNfc ? 'none' : '';
    el('qrg-nfc-buttons').style.display           = isNfc ? '' : 'none';
    el('qrg-preview-label').textContent           = isNfc ? 'NFC Tag' : 'Preview';
    el('qrg-status').style.display                = isNfc ? 'none' : '';
    if (isNfc) { var d = el('qrg-nfc-url-display'); if (d) d.textContent = 'https://pinplot.me/asset/' + (_currentNId || ''); }
    document.querySelectorAll('#qr-root .qrg-settings-panel').forEach(function(p) { p.classList.toggle('disabled', isNfc); });
    generate();
  }

  // ── Copy NFC URL ───────────────────────────────────────────
  function copyNfcUrl() {
    var url = 'https://pinplot.me/asset/' + (_currentNId || '');
    var btn = el('qrg-copy-btn');
    if (navigator.clipboard) {
      navigator.clipboard.writeText(url).then(function() {
        btn.textContent = '✓ Copied!'; btn.classList.add('copied');
        setTimeout(function(){ btn.textContent = '🔗 Copy NFC URL'; btn.classList.remove('copied'); }, 2000);
      });
    } else {
      var ta = document.createElement('textarea'); ta.value = url;
      document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
      btn.textContent = '✓ Copied!'; btn.classList.add('copied');
      setTimeout(function(){ btn.textContent = '🔗 Copy NFC URL'; btn.classList.remove('copied'); }, 2000);
    }
  }

  // ── Get text to encode ─────────────────────────────────────
  function getText() {
    if (mode === 'url') {
      if (!_currentQId) regenerateId('Q');
      return { text: 'https://pinplot.me/asset/' + _currentQId, ok: true };
    } else if (mode === 'nfc') {
      if (!_currentNId) regenerateId('N');
      return { text: 'https://pinplot.me/asset/' + _currentNId, ok: true };
    } else {
      var raw = (el('qrg-imei-input') || {}).value || '';
      raw = raw.trim();
      var lbl = (el('qrg-imei-label') || {}).value || '';
      lbl = lbl.trim();
      var imeiOk = /^\d{15}$/.test(raw);
      var macOk  = /^([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$/.test(raw);
      var errEl = el('qrg-imei-err');
      if (errEl) errEl.style.display = (raw.length > 0 && !imeiOk && !macOk) ? 'block' : 'none';
      var text = lbl ? lbl + ':' + raw : raw;
      return { text: text, ok: raw.length > 0 };
    }
  }

  // ── Color helpers ──────────────────────────────────────────
  function isValidHex(v) { return /^#[0-9A-Fa-f]{6}$/.test(v); }

  function getColor(id) {
    var hex = (el('qrg-' + id + '-hex') || {}).value || '';
    hex = hex.trim();
    if (/^[0-9A-Fa-f]{6}$/.test(hex)) hex = '#' + hex;
    if (isValidHex(hex)) return hex;
    return id === 'bg' ? '#ffffff' : '#000000';
  }

  function setColorValue(id, hex) {
    var col = el('qrg-' + id); if (col) col.value = hex;
    var hexEl = el('qrg-' + id + '-hex'); if (hexEl) hexEl.value = hex;
    var sw = el('qrg-' + id + '-swatch'); if (sw) sw.style.background = hex;
  }

  function syncHex(id) {
    var val = (el('qrg-' + id) || {}).value || '';
    var hexEl = el('qrg-' + id + '-hex'); if (hexEl) hexEl.value = val;
    var sw = el('qrg-' + id + '-swatch'); if (sw) sw.style.background = val;
    if (id === 'ic') { renderBuiltinIcon(); } else { generate(); }
  }

  function syncColor(id) {
    var raw = (el('qrg-' + id + '-hex') || {}).value || '';
    raw = raw.trim();
    if (/^[0-9A-Fa-f]{6}$/.test(raw)) raw = '#' + raw;
    var hexEl = el('qrg-' + id + '-hex'); if (hexEl) hexEl.value = raw;
    if (isValidHex(raw)) {
      var col = el('qrg-' + id); if (col) col.value = raw;
      var sw = el('qrg-' + id + '-swatch'); if (sw) sw.style.background = raw;
      if (id === 'ic') { renderBuiltinIcon(); } else { generate(); }
    }
  }

  function resetColors() {
    ['fg', 'bg'].forEach(function(id) { setColorValue(id, id === 'fg' ? '#000000' : '#ffffff'); });
    generate();
  }

  function resetCornerColors() {
    ['co', 'ci'].forEach(function(id) { setColorValue(id, '#000000'); });
    generate();
  }

  // ── Canvas drawing helpers ─────────────────────────────────
  function roundedRectPath(ctx, x, y, w, h, r) {
    ctx.moveTo(x+r, y); ctx.lineTo(x+w-r, y); ctx.arcTo(x+w, y, x+w, y+r, r);
    ctx.lineTo(x+w, y+h-r); ctx.arcTo(x+w, y+h, x+w-r, y+h, r);
    ctx.lineTo(x+r, y+h); ctx.arcTo(x, y+h, x, y+h-r, r);
    ctx.lineTo(x, y+r); ctx.arcTo(x, y, x+r, y, r); ctx.closePath();
  }
  function roundedRectFill(ctx, x, y, w, h, r) { ctx.beginPath(); roundedRectPath(ctx, x, y, w, h, r); ctx.fill(); }
  function roundBottomRect(ctx, x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x+w, y);
    ctx.lineTo(x+w, y+h-r); ctx.arcTo(x+w, y+h, x+w-r, y+h, r);
    ctx.lineTo(x+r, y+h); ctx.arcTo(x, y+h, x, y+h-r, r);
    ctx.lineTo(x, y); ctx.closePath(); ctx.fill();
  }
  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x+r, y); ctx.lineTo(x+w-r, y); ctx.arcTo(x+w, y, x+w, y+r, r);
    ctx.lineTo(x+w, y+h-r); ctx.arcTo(x+w, y+h, x+w-r, y+h, r);
    ctx.lineTo(x+r, y+h); ctx.arcTo(x, y+h, x, y+h-r, r);
    ctx.lineTo(x, y+r); ctx.arcTo(x, y, x+r, y, r); ctx.closePath(); ctx.fill();
  }

  // ── drawComposite ──────────────────────────────────────────
  function drawComposite(sz, fg, bg, srcCanvas) {
    var frame = activeFrame;
    var labelText = el('qrg-frame-label-text') ? (el('qrg-frame-label-text').value || 'PinPlot') : 'PinPlot';
    var DPR = 3;
    var src = srcCanvas || el('qrg-qr-canvas');
    var comp = el('qrg-composite-canvas');
    var ctx2 = comp.getContext('2d');
    var BANNER_H = frame !== 'none' ? Math.round(sz * 0.18) : 0;
    var PAD      = frame !== 'none' ? Math.round(sz * 0.04) : 0;
    var totalW = frame !== 'none' ? sz + PAD * 2 : sz;
    var totalH = frame !== 'none' ? sz + PAD * 2 + BANNER_H : sz;
    comp.width  = totalW * DPR; comp.height = totalH * DPR;
    comp.style.width = totalW + 'px'; comp.style.height = totalH + 'px';
    ctx2.setTransform(1,0,0,1,0,0); ctx2.scale(DPR, DPR);
    ctx2.imageSmoothingEnabled = false;
    if (frame === 'none') { ctx2.drawImage(src, 0, 0, totalW, totalH); return; }
    var radius = frame === 'bold' ? 12 : 6;
    if (frame === 'classic') {
      var cRad = Math.round(sz*0.07), badgeSz = Math.round(sz*0.12), badgePad = Math.round(sz*0.025);
      ctx2.fillStyle=fg; roundedRectFill(ctx2,0,0,totalW,totalH,cRad);
      ctx2.fillStyle=bg; roundedRectFill(ctx2,PAD*0.8,PAD*0.8,totalW-PAD*1.6,sz+PAD*1.2,Math.round(cRad*0.6));
      if(BANNER_H>0){var fs=Math.round(BANNER_H*0.46);ctx2.fillStyle=bg;ctx2.font='bold '+fs+'px sans-serif';ctx2.textAlign='left';ctx2.textBaseline='middle';ctx2.fillText(labelText,PAD*1.2,sz+PAD*2+BANNER_H/2);}
      ctx2.drawImage(src,PAD,PAD,sz,sz); return;
    } else if (frame === 'dashed') {
      ctx2.fillStyle=bg; ctx2.fillRect(0,0,totalW,totalH);
      ctx2.strokeStyle=fg; ctx2.lineWidth=2; ctx2.setLineDash([6,4]);
      ctx2.beginPath(); roundedRectPath(ctx2,1,1,totalW-2,totalH-2,radius); ctx2.stroke(); ctx2.setLineDash([]);
    } else if (frame === 'minimal') {
      ctx2.fillStyle=bg; ctx2.fillRect(0,0,totalW,totalH);
      var bl=14,bt=2; ctx2.strokeStyle=fg; ctx2.lineWidth=3; ctx2.lineCap='square';
      [[0,0],[totalW,0],[0,totalH],[totalW,totalH]].forEach(function(c){var sx=c[0]===0?bt:totalW-bt,sy=c[1]===0?bt:totalH-bt,dx=c[0]===0?1:-1,dy=c[1]===0?1:-1;ctx2.beginPath();ctx2.moveTo(sx,sy);ctx2.lineTo(sx+dx*bl,sy);ctx2.stroke();ctx2.beginPath();ctx2.moveTo(sx,sy);ctx2.lineTo(sx,sy+dy*bl);ctx2.stroke();});
    } else if (frame === 'stamp') {
      ctx2.fillStyle=bg; ctx2.fillRect(0,0,totalW,totalH);
      ctx2.strokeStyle=fg; ctx2.lineWidth=2.5; ctx2.setLineDash([5,3]);
      ctx2.beginPath(); roundedRectPath(ctx2,1.5,1.5,totalW-3,totalH-3,4); ctx2.stroke(); ctx2.setLineDash([]);
      ctx2.fillStyle=fg; roundedRectFill(ctx2,0,sz+PAD*2,totalW,BANNER_H,4);
    } else if (frame === 'ticket') {
      ctx2.fillStyle=fg; roundedRectFill(ctx2,0,0,totalW,totalH,12);
      ctx2.fillStyle=bg; roundedRectFill(ctx2,PAD*0.8,PAD*0.8,totalW-PAD*1.6,sz+PAD*1.2,8);
      var tearY=sz+PAD*2,notchR=PAD*0.9;
      ctx2.save(); ctx2.strokeStyle=bg; ctx2.lineWidth=1.5; ctx2.setLineDash([4,4]); ctx2.globalAlpha=0.4;
      ctx2.beginPath(); ctx2.moveTo(PAD*2,tearY); ctx2.lineTo(totalW-PAD*2,tearY); ctx2.stroke();
      ctx2.setLineDash([]); ctx2.globalAlpha=1; ctx2.restore();
      ctx2.fillStyle=bg; ctx2.beginPath(); ctx2.arc(-notchR*0.4,tearY,notchR,0,Math.PI*2); ctx2.fill();
      ctx2.beginPath(); ctx2.arc(totalW+notchR*0.4,tearY,notchR,0,Math.PI*2); ctx2.fill();
      if(BANNER_H>0){var fs=Math.round(BANNER_H*0.46);ctx2.fillStyle=bg;ctx2.font='bold '+fs+'px sans-serif';ctx2.textAlign='center';ctx2.textBaseline='middle';ctx2.fillText(labelText,totalW/2,sz+PAD*2+BANNER_H/2);}
      ctx2.drawImage(src,PAD,PAD,sz,sz); return;
    } else {
      ctx2.fillStyle = frame==='bold' ? fg : bg;
      roundedRectFill(ctx2,0,0,totalW,totalH,radius);
      if(frame==='bold'){ctx2.fillStyle=bg;roundedRectFill(ctx2,PAD*0.6,PAD*0.6,totalW-PAD*1.2,sz+PAD*1.4,radius*0.6);}
      ctx2.fillStyle=fg; roundBottomRect(ctx2,0,sz+PAD*2,totalW,BANNER_H,radius);
    }
    ctx2.drawImage(src, PAD, PAD, sz, sz);
    if (BANNER_H > 0) {
      var textColor = (frame==='dashed'||frame==='minimal') ? fg : bg;
      var fs = Math.round(BANNER_H*0.48);
      ctx2.fillStyle=textColor; ctx2.font='bold '+fs+'px sans-serif';
      ctx2.textAlign='center'; ctx2.textBaseline='middle';
      ctx2.fillText(labelText, totalW/2, sz+PAD*2+BANNER_H/2);
    }
  }

  // ── drawIcon ───────────────────────────────────────────────
  function drawIcon(ctx, canvasSz, sz, bg, callback) {
    var pct = parseInt((el('qrg-isize')||{value:'20'}).value) / 100;
    var isz = Math.round(canvasSz * pct);
    var ix = (canvasSz - isz) / 2, iy = (canvasSz - isz) / 2;
    var img = new Image();
    img.onload = function() {
      ctx.imageSmoothingEnabled=true; ctx.imageSmoothingQuality='high';
      var pad = Math.round(canvasSz*0.018);
      ctx.fillStyle=bg; roundRect(ctx,ix-pad,iy-pad,isz+pad*2,isz+pad*2,pad*1.5);
      ctx.drawImage(img,ix,iy,isz,isz);
      if (callback) callback();
    };
    img.src = iconData;
  }

  // ── Main generate ──────────────────────────────────────────
  function generate() { clearTimeout(gtimer); gtimer = setTimeout(_gen, 80); }

  function _gen() {
    var t = getText();
    var canvas = el('qrg-qr-canvas');
    var ctx = canvas.getContext('2d');
    var st  = el('qrg-status');
    if (!t.ok) { ctx.clearRect(0,0,canvas.width,canvas.height); if(st) st.textContent='Enter content above'; return; }

    var sz  = parseInt((el('qrg-qsize')||{value:'256'}).value);
    var fg  = getColor('fg');
    var bg  = getColor('bg');
    var co  = getColor('co');
    var ci  = getColor('ci');
    var sty = (el('qrg-mstyle')||{value:'square'}).value;
    var ecc = (el('qrg-ecc')||{value:'Q'}).value;
    if (iconData) ecc = 'H';

    var DPR = 3, rsz = sz * DPR;
    try {
      var qr = qrcode(0, ecc);
      qr.addData(t.text, 'Byte'); qr.make();
      var mc = qr.getModuleCount();
      ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
      var QZ = 4, totalMods = mc + QZ * 2;
      var ms = Math.floor(rsz / totalMods);
      var actualSz = ms * totalMods;
      canvas.width = actualSz; canvas.height = actualSz;
      canvas.style.width = sz + 'px'; canvas.style.height = sz + 'px';
      var offset = QZ * ms;
      ctx.fillStyle = bg; ctx.fillRect(0, 0, rsz, rsz);
      ctx.fillStyle = fg;

      function finderRole(r, c) {
        var corners=[[0,0],[0,mc-7],[mc-7,0]];
        for(var i=0;i<corners.length;i++){var tr=corners[i][0],tc=corners[i][1],dr=r-tr,dc=c-tc;if(dr>=0&&dr<=6&&dc>=0&&dc<=6){if(dr>=2&&dr<=4&&dc>=2&&dc<=4)return 'inner';if(dr===0||dr===6||dc===0||dc===6)return 'outer';return 'gap';}}
        return 'data';
      }

      function drawModule(c, r2, c2, dark, overrideFg) {
        var x=offset+c2*ms, y=offset+r2*ms, color=overrideFg||(dark?fg:bg);
        c.fillStyle=color;
        if(sty==='dots'){c.beginPath();c.arc(x+ms/2,y+ms/2,ms*0.44,0,Math.PI*2);c.fill();}
        else if(sty==='rounded'){roundRect(c,x+0.5,y+0.5,ms-1,ms-1,ms*0.28);}
        else{c.fillRect(x,y,ms,ms);}
      }

      for(var r=0;r<mc;r++)for(var c2=0;c2<mc;c2++){
        if(!qr.isDark(r,c2))continue;
        var role=finderRole(r,c2);
        if(role==='outer') drawModule(ctx,r,c2,true,co);
        else if(role==='inner') drawModule(ctx,r,c2,true,ci);
        else if(role!=='gap') drawModule(ctx,r,c2,true,null);
      }

      // corrupted preview
      function isFunctional(r2,c2){
        if(r2<=8&&c2<=8)return true; if(r2<=8&&c2>=mc-8)return true; if(r2>=mc-8&&c2<=8)return true;
        if(r2===6||c2===6)return true; return false;
      }
      var flippable=[];
      for(var r=0;r<mc;r++)for(var c2=0;c2<mc;c2++)if(!isFunctional(r,c2)&&qr.isDark(r,c2))flippable.push([r,c2]);
      var seed=0; for(var i=0;i<t.text.length;i++)seed=(seed*31+t.text.charCodeAt(i))&0xffffffff;
      function seededRand(){seed=(seed*1664525+1013904223)&0xffffffff;return(seed>>>0)/0xffffffff;}
      flippable.sort(function(){return seededRand()-0.5;});
      var eccFlipRate={L:0.18,M:0.28,Q:0.42,H:0.50};
      var rate=eccFlipRate[ecc]||0.28, flipCount=Math.max(10,Math.floor(flippable.length*rate));
      var flipped={};
      for(var i=0;i<flipCount;i++){var m=flippable[i];flipped[m[0]+','+m[1]]=true;}

      var previewCanvas=document.createElement('canvas');
      previewCanvas.width=actualSz; previewCanvas.height=actualSz;
      var pctx=previewCanvas.getContext('2d');
      pctx.imageSmoothingEnabled=true; pctx.imageSmoothingQuality='high';
      pctx.fillStyle=bg; pctx.fillRect(0,0,rsz,rsz); pctx.fillStyle=fg;
      for(var r=0;r<mc;r++)for(var c2=0;c2<mc;c2++){
        var key=r+','+c2, dark=flipped[key]?false:qr.isDark(r,c2);
        if(!dark)continue;
        var role2=finderRole(r,c2); if(role2==='gap')continue;
        var x=offset+c2*ms, y=offset+r*ms;
        pctx.fillStyle=role2==='outer'?co:role2==='inner'?ci:fg;
        if(sty==='dots'){pctx.beginPath();pctx.arc(x+ms/2,y+ms/2,ms*0.44,0,Math.PI*2);pctx.fill();}
        else if(sty==='rounded'){roundRect(pctx,x+0.5,y+0.5,ms-1,ms-1,ms*0.28);}
        else{pctx.fillRect(x,y,ms,ms);}
      }

      if(iconData){
        drawIcon(pctx,actualSz,sz,bg,function(){drawComposite(sz,fg,bg,previewCanvas);});
      } else {
        drawComposite(sz,fg,bg,previewCanvas);
      }

      var modeLabel=mode==='imei'?'plain text':mode==='nfc'?'NFC tag URL':'asset URL';
      if(st) st.textContent='v'+qr.getModuleCount()+'mod — '+t.text.length+' chars — '+modeLabel;
    } catch(e) { if(st) st.textContent='Error: '+e.message; }
  }

  // ── Export clean (for downloads) ───────────────────────────
  function exportClean(callback) {
    var t = getText(); if (!t.ok) return;
    var sz = parseInt((el('qrg-qsize')||{value:'256'}).value);
    var fg=getColor('fg'), bg=getColor('bg'), co=getColor('co'), ci=getColor('ci');
    var sty=(el('qrg-mstyle')||{value:'square'}).value;
    var ecc=(el('qrg-ecc')||{value:'Q'}).value;
    if(iconData) ecc='H';
    var frame=activeFrame, labelText=(el('qrg-frame-label-text')||{value:'PinPlot'}).value||'PinPlot';
    var qr; try{qr=qrcode(0,ecc);qr.addData(t.text,'Byte');qr.make();}catch(e){console.error(e);return;}
    var mc=qr.getModuleCount(), QZ=4, DPR=3;
    var px=Math.floor((sz*DPR)/(mc+QZ*2)); if(px<1)px=1;
    var side=px*(mc+QZ*2);
    var qrOff=document.createElement('canvas'); qrOff.width=side; qrOff.height=side;
    var qctx=qrOff.getContext('2d'); qctx.imageSmoothingEnabled=false;
    qctx.fillStyle=bg; qctx.fillRect(0,0,side,side); qctx.fillStyle=fg;
    for(var row=0;row<mc;row++)for(var col=0;col<mc;col++){
      if(!qr.isDark(row,col))continue;
      var x=(QZ+col)*px, y=(QZ+row)*px, color=fg, isCorner=false;
      var corners=[[0,0],[0,mc-7],[mc-7,0]];
      for(var k=0;k<corners.length;k++){var dr=row-corners[k][0],dc=col-corners[k][1];if(dr>=0&&dr<=6&&dc>=0&&dc<=6){isCorner=true;if(dr===1||dr===5||dc===1||dc===5){qctx.fillStyle=bg;qctx.fillRect(x,y,px,px);color=null;}else if(dr>=2&&dr<=4&&dc>=2&&dc<=4){color=ci;}else{color=co;}break;}}
      if(color===null)continue; qctx.fillStyle=color;
      if(sty==='dots'){qctx.beginPath();qctx.arc(x+px/2,y+px/2,px*0.44,0,Math.PI*2);qctx.fill();}
      else if(sty==='rounded'){var rad=px*0.28;qctx.beginPath();qctx.moveTo(x+rad,y);qctx.lineTo(x+px-rad,y);qctx.arcTo(x+px,y,x+px,y+rad,rad);qctx.lineTo(x+px,y+px-rad);qctx.arcTo(x+px,y+px,x+px-rad,y+px,rad);qctx.lineTo(x+rad,y+px);qctx.arcTo(x,y+px,x,y+px-rad,rad);qctx.lineTo(x,y+rad);qctx.arcTo(x,y,x+rad,y,rad);qctx.closePath();qctx.fill();}
      else{qctx.fillRect(x,y,px,px);}
    }
    var BANNER_H=frame!=='none'?Math.round(sz*0.18):0, PAD=frame!=='none'?Math.round(sz*0.04):0;
    var dispSz=side/DPR, totalW=frame==='none'?dispSz:dispSz+PAD*2, totalH=frame==='none'?dispSz:dispSz+PAD*2+BANNER_H;
    var compOff=document.createElement('canvas'); compOff.width=Math.round(totalW*DPR); compOff.height=Math.round(totalH*DPR);
    var cCtx=compOff.getContext('2d'); cCtx.setTransform(1,0,0,1,0,0); cCtx.scale(DPR,DPR); cCtx.imageSmoothingEnabled=false;
    if(frame==='none'){cCtx.drawImage(qrOff,0,0,totalW,totalH);}
    else{
      var radius=frame==='bold'?12:6;
      if(frame==='dashed'){cCtx.fillStyle=bg;cCtx.fillRect(0,0,totalW,totalH);cCtx.strokeStyle=fg;cCtx.lineWidth=2;cCtx.setLineDash([6,4]);cCtx.beginPath();roundedRectPath(cCtx,1,1,totalW-2,totalH-2,radius);cCtx.stroke();cCtx.setLineDash([]);}
      else if(frame==='minimal'){cCtx.fillStyle=bg;cCtx.fillRect(0,0,totalW,totalH);var bl=14,bt=2;cCtx.strokeStyle=fg;cCtx.lineWidth=3;cCtx.lineCap='square';[[0,0],[totalW,0],[0,totalH],[totalW,totalH]].forEach(function(cr){var sx=cr[0]===0?bt:totalW-bt,sy=cr[1]===0?bt:totalH-bt,dx=cr[0]===0?1:-1,dy=cr[1]===0?1:-1;cCtx.beginPath();cCtx.moveTo(sx,sy);cCtx.lineTo(sx+dx*bl,sy);cCtx.stroke();cCtx.beginPath();cCtx.moveTo(sx,sy);cCtx.lineTo(sx,sy+dy*bl);cCtx.stroke();});}
      else if(frame==='ticket'){cCtx.fillStyle=fg;roundedRectFill(cCtx,0,0,totalW,totalH,12);cCtx.fillStyle=bg;roundedRectFill(cCtx,PAD*0.8,PAD*0.8,totalW-PAD*1.6,dispSz+PAD*1.2,8);var tearY2=dispSz+PAD*2,notchR2=PAD*0.9;cCtx.save();cCtx.strokeStyle=bg;cCtx.lineWidth=1.5;cCtx.setLineDash([4,4]);cCtx.globalAlpha=0.4;cCtx.beginPath();cCtx.moveTo(PAD*2,tearY2);cCtx.lineTo(totalW-PAD*2,tearY2);cCtx.stroke();cCtx.setLineDash([]);cCtx.globalAlpha=1;cCtx.restore();cCtx.fillStyle=bg;cCtx.beginPath();cCtx.arc(-notchR2*0.4,tearY2,notchR2,0,Math.PI*2);cCtx.fill();cCtx.beginPath();cCtx.arc(totalW+notchR2*0.4,tearY2,notchR2,0,Math.PI*2);cCtx.fill();if(BANNER_H>0){var f3=Math.round(BANNER_H*0.46);cCtx.fillStyle=bg;cCtx.font='bold '+f3+'px sans-serif';cCtx.textAlign='center';cCtx.textBaseline='middle';cCtx.fillText(labelText,totalW/2,dispSz+PAD*2+BANNER_H/2);}}
      else if(frame==='classic'){var cRad2=Math.round(dispSz*0.07),badgeSz2=Math.round(dispSz*0.12),badgePad2=Math.round(dispSz*0.025);cCtx.fillStyle=fg;roundedRectFill(cCtx,0,0,totalW,totalH,cRad2);cCtx.fillStyle=bg;roundedRectFill(cCtx,PAD*0.8,PAD*0.8,totalW-PAD*1.6,dispSz+PAD*1.2,Math.round(cRad2*0.6));if(BANNER_H>0){var f4=Math.round(BANNER_H*0.46);cCtx.fillStyle=bg;cCtx.font='bold '+f4+'px sans-serif';cCtx.textAlign='left';cCtx.textBaseline='middle';cCtx.fillText(labelText,PAD*1.2,dispSz+PAD*2+BANNER_H/2);}}
      else{cCtx.fillStyle=frame==='bold'?fg:bg;roundedRectFill(cCtx,0,0,totalW,totalH,radius);if(frame==='bold'){cCtx.fillStyle=bg;roundedRectFill(cCtx,PAD*0.6,PAD*0.6,totalW-PAD*1.2,dispSz+PAD*1.4,radius*0.6);}if(frame==='stamp'){cCtx.strokeStyle=fg;cCtx.lineWidth=2.5;cCtx.setLineDash([5,3]);cCtx.beginPath();roundedRectPath(cCtx,1.5,1.5,totalW-3,totalH-3,4);cCtx.stroke();cCtx.setLineDash([]);}cCtx.fillStyle=fg;roundBottomRect(cCtx,0,dispSz+PAD*2,totalW,BANNER_H,radius);if(BANNER_H>0){var f5=Math.round(BANNER_H*0.46);cCtx.fillStyle=bg;cCtx.font='bold '+f5+'px sans-serif';cCtx.textAlign='center';cCtx.textBaseline='middle';cCtx.fillText(labelText,totalW/2,dispSz+PAD*2+BANNER_H/2);}}
      cCtx.imageSmoothingEnabled=false; cCtx.drawImage(qrOff,PAD,PAD,dispSz,dispSz);
    }
    if(iconData){
      var pct=parseInt((el('qrg-isize')||{value:'20'}).value)/100, isz=Math.round(dispSz*pct);
      var ix=(frame==='none'?0:PAD)+(dispSz-isz)/2, iy=(frame==='none'?0:PAD)+(dispSz-isz)/2;
      var img2=new Image(); img2.onload=function(){
        cCtx.imageSmoothingEnabled=true; cCtx.imageSmoothingQuality='high';
        var pad2=Math.round(dispSz*0.018); cCtx.fillStyle=bg;
        roundedRectFill(cCtx,ix-pad2,iy-pad2,isz+pad2*2,isz+pad2*2,pad2*1.5);
        cCtx.drawImage(img2,ix,iy,isz,isz);
        callback(compOff.toDataURL('image/png'),Math.round(totalW),Math.round(totalH));
      }; img2.src=iconData;
    } else {
      callback(compOff.toDataURL('image/png'),Math.round(totalW),Math.round(totalH));
    }
  }

  function slugName() {
    var t=getText().text; return t.replace(/[^a-zA-Z0-9]/g,'_').substring(0,24)||'qrcode';
  }

  function dlPNG() {
    exportClean(function(dataURL){
      var a=document.createElement('a'); a.href=dataURL; a.download=slugName()+'.png';
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
    });
  }

  function dlSVG() {
    exportClean(function(dataURL,w,h){
      var svgStr='<svg xmlns="http://www.w3.org/2000/svg" width="'+w+'" height="'+h+'">'
        +'<image href="'+dataURL+'" width="'+w+'" height="'+h+'"/></svg>';
      var blob=new Blob([svgStr],{type:'image/svg+xml'});
      var url=URL.createObjectURL(blob);
      var a=document.createElement('a'); a.href=url; a.download=slugName()+'.svg';
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(function(){URL.revokeObjectURL(url);},10000);
    });
  }

  // ── Icon handling ──────────────────────────────────────────
  var BUILTIN_ICONS = [
    { id:'box',      label:'Box',      path:'M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5' },
    { id:'track',    label:'Track',    path:'M9 17H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5M13 21l4-4-4-4M17 17H9' },
    { id:'truck',    label:'Truck',    path:'M1 3h15v13H1zM16 8h4l3 3v5h-7V8zM5.5 19a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM18.5 19a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z' },
    { id:'laptop',   label:'Laptop',   path:'M4 2h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1zM1 21h22M9 17l1 4M15 17l-1 4' },
    { id:'pin',      label:'Location', path:'M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zM12 11.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5z' },
    { id:'building', label:'Building', path:'M3 21h18M5 21V7l7-4 7 4v14M9 21v-4h6v4M9 9h2M13 9h2M9 13h2M13 13h2' },
    { id:'people',   label:'People',   path:'M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75' },
    { id:'scan',     label:'Scan',     path:'M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2M7 8h10M7 12h10M7 16h6' },
    { id:'wifi',     label:'WiFi',     path:'M5 12.55a11 11 0 0 1 14.08 0M1.42 9a16 16 0 0 1 21.16 0M8.53 16.11a6 6 0 0 1 6.95 0M12 20h.01' }
  ];

  function buildIconGrid() {
    var grid = el('qrg-icon-grid'); if (!grid) return;
    grid.innerHTML = '';
    var noneDiv = document.createElement('div');
    noneDiv.className = 'qrg-icon-opt' + (activeIconId === null ? ' active' : '');
    noneDiv.innerHTML = '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><line x1="5" y1="5" x2="19" y2="19" stroke="#bbb" stroke-width="2"/><line x1="19" y1="5" x2="5" y2="19" stroke="#bbb" stroke-width="2"/></svg><span>None</span>';
    noneDiv.onclick = function() { selectBuiltinIcon(null); };
    grid.appendChild(noneDiv);
    var isDark = document.documentElement.getAttribute('data-theme') !== 'light';
    BUILTIN_ICONS.forEach(function(ic) {
      var div = document.createElement('div');
      div.className = 'qrg-icon-opt' + (activeIconId === ic.id ? ' active' : '');
      var stroke = isDark ? '#c8d8e8' : '#333';
      div.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="'+stroke+'" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg"><path d="'+ic.path+'"/></svg><span>'+ic.label+'</span>';
      div.onclick = function() { selectBuiltinIcon(ic.id); };
      grid.appendChild(div);
    });
  }

  function selectBuiltinIcon(id) {
    activeIconId = id;
    document.querySelectorAll('#qr-root .qrg-icon-opt').forEach(function(e){ e.classList.remove('active'); });
    var opts = document.querySelectorAll('#qr-root .qrg-icon-opt');
    var idx = id === null ? 0 : BUILTIN_ICONS.findIndex(function(ic){ return ic.id === id; }) + 1;
    if (opts[idx]) opts[idx].classList.add('active');
    renderBuiltinIcon();
  }

  function renderBuiltinIcon() {
    if (activeIconId === null) { iconData = null; var w=el('qrg-isizewrap'); if(w)w.style.display='none'; generate(); return; }
    var ic = BUILTIN_ICONS.find(function(x){ return x.id === activeIconId; }); if (!ic) return;
    var color = getColor('ic');
    var svgStr = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="'+color+'" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="'+ic.path+'"/></svg>';
    var blob = new Blob([svgStr], {type:'image/svg+xml'});
    var url  = URL.createObjectURL(blob);
    var img  = new Image();
    img.onload = function() {
      var c = document.createElement('canvas'); c.width=128; c.height=128;
      var ctx=c.getContext('2d'); ctx.drawImage(img,0,0,128,128);
      iconData = c.toDataURL('image/png');
      URL.revokeObjectURL(url);
      var w=el('qrg-isizewrap'); if(w)w.style.display='';
      generate();
    };
    img.src = url;
  }

  function setIconSource(src) {
    iconSource = src;
    var pt=el('qrg-tab-preset'), ut=el('qrg-tab-upload');
    if(pt) pt.className='qrg-icon-source-tab'+(src==='preset'?' active':'');
    if(ut) ut.className='qrg-icon-source-tab'+(src==='upload'?' active':'');
    var pp=el('qrg-icon-preset-panel'), up=el('qrg-icon-upload-panel');
    if(pp) pp.style.display=src==='preset'?'':'none';
    if(up) up.style.display=src==='upload'?'':'none';
    if(src==='preset'){ renderBuiltinIcon(); } else { activeIconId=null; }
  }

  function loadIconFile(e) {
    var f = e.target.files[0]; if (!f) return;
    var r = new FileReader();
    r.onload = function(ev) {
      iconData = ev.target.result;
      var prev=el('qrg-icon-preview'); if(prev)prev.src=iconData;
      var row=el('qrg-icon-preview-row'); if(row)row.style.display='flex';
      var w=el('qrg-isizewrap'); if(w)w.style.display='';
      generate();
    };
    r.readAsDataURL(f);
  }

  function removeIcon() {
    iconData=null;
    var fi=el('qrg-iconfile'); if(fi)fi.value='';
    var prev=el('qrg-icon-preview'); if(prev)prev.src='';
    var row=el('qrg-icon-preview-row'); if(row)row.style.display='none';
    var w=el('qrg-isizewrap'); if(w)w.style.display='none';
    generate();
  }

  // ── Frame grid ─────────────────────────────────────────────
  var FRAMES = [
    {id:'none',    label:'None',          hasLabel:false},
    {id:'banner',  label:'Bottom banner', hasLabel:true},
    {id:'bold',    label:'Bold banner',   hasLabel:true},
    {id:'classic', label:'Classic card',  hasLabel:true},
    {id:'stamp',   label:'Stamp',         hasLabel:true},
    {id:'dashed',  label:'Dashed border', hasLabel:false},
    {id:'ticket',  label:'Ticket',        hasLabel:true},
    {id:'minimal', label:'Minimal',       hasLabel:false}
  ];

  function frameSVG(id) {
    var q='<rect x="5" y="3" width="34" height="34" rx="2" fill="#eee"/><rect x="9" y="7" width="26" height="26" rx="1" fill="#bbb"/>';
    switch(id){
      case 'none':    return '<svg viewBox="0 0 44 52" xmlns="http://www.w3.org/2000/svg"><line x1="10" y1="22" x2="34" y2="22" stroke="#bbb" stroke-width="2"/><line x1="22" y1="10" x2="22" y2="34" stroke="#bbb" stroke-width="2"/><circle cx="22" cy="22" r="12" stroke="#bbb" stroke-width="2" fill="none"/></svg>';
      case 'banner':  return '<svg viewBox="0 0 44 52" xmlns="http://www.w3.org/2000/svg">'+q+'<rect x="5" y="38" width="34" height="12" rx="2" fill="#333"/><text x="22" y="48" font-size="6" fill="#fff" text-anchor="middle" font-family="sans-serif">PinPlot</text></svg>';
      case 'bold':    return '<svg viewBox="0 0 44 52" xmlns="http://www.w3.org/2000/svg"><rect x="3" y="2" width="38" height="38" rx="3" fill="#222"/><rect x="7" y="5" width="30" height="30" rx="2" fill="#fff"/><rect x="9" y="7" width="26" height="26" rx="1" fill="#ddd"/><rect x="3" y="38" width="38" height="12" rx="2" fill="#222"/><text x="22" y="48" font-size="7" fill="#fff" text-anchor="middle" font-family="sans-serif" font-weight="bold">PinPlot</text></svg>';
      case 'classic': return '<svg viewBox="0 0 44 54" xmlns="http://www.w3.org/2000/svg"><rect x="1" y="1" width="42" height="52" rx="7" fill="#111"/><rect x="4" y="3" width="36" height="36" rx="5" fill="#fff"/><rect x="7" y="6" width="30" height="30" rx="2" fill="#ddd"/><text x="18" y="49" font-size="5.5" fill="#fff" text-anchor="middle" font-family="sans-serif" font-weight="bold">PinPlot</text></svg>';
      case 'stamp':   return '<svg viewBox="0 0 44 52" xmlns="http://www.w3.org/2000/svg"><rect x="3" y="2" width="38" height="38" rx="2" fill="none" stroke="#333" stroke-width="2" stroke-dasharray="3,2"/>'+q+'<rect x="5" y="38" width="34" height="12" rx="2" fill="#333"/><text x="22" y="48" font-size="6" fill="#fff" text-anchor="middle" font-family="sans-serif">PinPlot</text></svg>';
      case 'dashed':  return '<svg viewBox="0 0 44 52" xmlns="http://www.w3.org/2000/svg"><rect x="3" y="8" width="38" height="38" rx="3" fill="none" stroke="#333" stroke-width="2" stroke-dasharray="4,3"/><rect x="5" y="10" width="34" height="34" rx="2" fill="#eee"/><rect x="9" y="14" width="26" height="26" rx="1" fill="#bbb"/></svg>';
      case 'ticket':  return '<svg viewBox="0 0 44 52" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="2" width="40" height="48" rx="4" fill="#222"/><rect x="5" y="4" width="34" height="34" rx="2" fill="#fff"/><rect x="9" y="7" width="26" height="26" rx="1" fill="#ddd"/><text x="22" y="47" font-size="5.5" fill="#fff" text-anchor="middle" font-family="sans-serif" font-weight="bold">PinPlot</text></svg>';
      case 'minimal': return '<svg viewBox="0 0 44 52" xmlns="http://www.w3.org/2000/svg"><rect x="3" y="6" width="8" height="8" rx="1" fill="none" stroke="#333" stroke-width="2"/><rect x="33" y="6" width="8" height="8" rx="1" fill="none" stroke="#333" stroke-width="2"/><rect x="3" y="30" width="8" height="8" rx="1" fill="none" stroke="#333" stroke-width="2"/>'+q+'</svg>';
      default:        return '<svg viewBox="0 0 44 52" xmlns="http://www.w3.org/2000/svg"/>';
    }
  }

  function buildFrameGrid() {
    var grid = el('qrg-frame-grid'); if (!grid) return;
    grid.innerHTML = '';
    FRAMES.forEach(function(f) {
      var div = document.createElement('div');
      div.className = 'qrg-frame-opt' + (f.id === 'none' ? ' active' : '');
      div.innerHTML = frameSVG(f.id) + '<span>' + f.label + '</span>';
      div.onclick = function() {
        activeFrame = f.id;
        document.querySelectorAll('#qr-root .qrg-frame-opt').forEach(function(e){ e.classList.remove('active'); });
        div.classList.add('active');
        var lw = el('qrg-frame-label-wrap');
        if (lw) lw.className = 'qrg-frame-label-wrap' + (f.hasLabel ? ' visible' : '');
        generate();
      };
      grid.appendChild(div);
    });
  }

  // ── Colour presets ─────────────────────────────────────────
  var COLOR_PRESETS = [
    {fg:'#000000',bg:'#ffffff',label:'Classic'},{fg:'#006400',bg:'#ffffff',label:'Forest'},
    {fg:'#1a237e',bg:'#ffffff',label:'Navy'},{fg:'#b71c1c',bg:'#ffffff',label:'Red'},
    {fg:'#4a2800',bg:'#ffd54f',label:'Amber'},{fg:'#000000',bg:'#e8f5e9',label:'Mint'},
    {fg:'#000080',bg:'#ffffff',label:'Royal'},{fg:'#008080',bg:'#d3d3d3',label:'Teal'},
    {fg:'#228b22',bg:'#f5f5dc',label:'Sage'},{fg:'#8b0000',bg:'#ffffe0',label:'Crimson'},
    {fg:'#800020',bg:'#fffdd0',label:'Burgundy'},{fg:'#301934',bg:'#e6e6fa',label:'Plum'},
    {fg:'#36454f',bg:'#ffd580',label:'Charcoal'}
  ];

  function buildPresetGrid() {
    var grid = el('qrg-preset-grid'); if (!grid) return;
    grid.innerHTML = '';
    COLOR_PRESETS.forEach(function(p, i) {
      var div = document.createElement('div');
      div.className = 'qrg-preset-opt' + (i === 0 ? ' active' : '');
      div.title = p.label;
      div.innerHTML = '<div class="qrg-preset-swatch" style="background:'+p.fg+'"></div><div class="qrg-preset-swatch" style="background:'+p.bg+'"></div>';
      div.onclick = function() {
        document.querySelectorAll('#qr-root .qrg-preset-opt').forEach(function(e){ e.classList.remove('active'); });
        div.classList.add('active');
        setColorValue('fg', p.fg); setColorValue('bg', p.bg); generate();
      };
      grid.appendChild(div);
    });
  }

  // ── Public API ─────────────────────────────────────────────
  var _initialized = false;

  function init() {
    if (_initialized) return;
    _initialized = true;
    buildFrameGrid();
    buildPresetGrid();
    buildIconGrid();
    regenerateId('Q');
    regenerateId('N');
    generate();
  }

  function onShow() {
    // Called by switchTab('qr') — init on first show, regenerate on subsequent shows
    if (!_initialized) { init(); return; }
    generate();
  }

  // Expose minimal public surface
  return {
    onShow: onShow,
    setMode: setMode,
    regenerateId: regenerateId,
    syncHex: syncHex,
    syncColor: syncColor,
    setColorValue: setColorValue,
    resetColors: resetColors,
    resetCornerColors: resetCornerColors,
    getColor: getColor,
    setIconSource: setIconSource,
    loadIconFile: loadIconFile,
    removeIcon: removeIcon,
    renderBuiltinIcon: renderBuiltinIcon,
    copyNfcUrl: copyNfcUrl,
    generate: generate,
    dlPNG: dlPNG,
    dlSVG: dlSVG
  };
})();
