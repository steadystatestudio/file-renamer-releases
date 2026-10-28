function WideSplitString(const Input, Delimiter: WideString): TWideStringArray;
var Rest: WideString; P,N: Integer;
begin
  SetLength(Result,0); Rest:=Input;
  if Delimiter='' then begin SetLength(Result,1); Result[0]:=Input; Exit; end;
  repeat
    P:=WidePos(Delimiter,Rest); N:=Length(Result); SetLength(Result,N+1);
    if P=0 then begin Result[N]:=Rest; Exit; end;
    Result[N]:=WideCopy(Rest,1,P-1); WideDelete(Rest,1,P+WideLength(Delimiter)-1);
  until False;
end;
function WideJoinStrings(const Strings: TWideStringArray; const Delimiter: WideString): WideString;
var I: Integer;
begin
  Result:=''; for I:=0 to Length(Strings)-1 do begin
    if I>0 then Result:=Result+Delimiter; Result:=Result+Strings[I];
  end;
end;
procedure WideAppendStringArray(var Strings: TWideStringArray; const NewString: WideString);
var N: Integer;
begin N:=Length(Strings); SetLength(Strings,N+1); Strings[N]:=NewString; end;
function WideCopyStringArray(const Strings: TWideStringArray; Index,Count: Integer): TWideStringArray;
var I,N: Integer;
begin
  if Index<0 then Index:=0; N:=Length(Strings)-Index;
  if N<0 then N:=0; if Count<N then N:=Count; if N<0 then N:=0;
  SetLength(Result,N); for I:=0 to N-1 do Result[I]:=Strings[Index+I];
end;
function WideConcatStringArrays(const A,B: TWideStringArray): TWideStringArray;
var I,N: Integer;
begin
  N:=Length(A); SetLength(Result,N+Length(B));
  for I:=0 to N-1 do Result[I]:=A[I];
  for I:=0 to Length(B)-1 do Result[N+I]:=B[I];
end;
function WideCaseSentence(const S: WideString): WideString;
begin Result:=WideLowerCase(S); if WideLength(Result)>0 then
  Result:=WideUpperCase(WideCopy(Result,1,1))+WideCopy(Result,2,WideLength(Result)); end;
function WideCaseCapitalize(const S: WideString): WideString;
var I: Integer; Boundary: Boolean; C: WideString;
begin
  Result:=''; Boundary:=True;
  for I:=1 to WideLength(S) do begin C:=WideCopy(S,I,1);
    if Boundary then C:=WideUpperCase(C) else C:=WideLowerCase(C);
    Result:=Result+C; Boundary:=WidePos(C,' _-.()[]{}')>0;
  end;
end;
function WideCaseInvert(const S: WideString): WideString;
var I: Integer; C: WideString;
begin Result:=''; for I:=1 to WideLength(S) do begin C:=WideCopy(S,I,1);
  if C=WideUpperCase(C) then Result:=Result+WideLowerCase(C) else Result:=Result+WideUpperCase(C);
end; end;
function FileReadTextLines(const FileName: WideString): TWideStringArray;
begin Result:=WideSplitString(WideReplaceStr(FileReadText(FileName),#13#10,#10),#10); end;
function FileReadLines(const FileName: WideString): TAnsiStringArray;
var W: TWideStringArray; I: Integer;
begin W:=FileReadTextLines(FileName); SetLength(Result,Length(W));
  for I:=0 to Length(W)-1 do Result[I]:=UTF8Encode(W[I]); end;
function FileReadLine(const FileName: WideString; LineNum: Integer): String;
var A: TAnsiStringArray;
begin A:=FileReadLines(FileName); Result:=''; if (LineNum>0) and (LineNum<=Length(A)) then Result:=A[LineNum-1]; end;
function FileCountLines(const FileName: WideString): Integer;
begin Result:=Length(FileReadLines(FileName)); end;
function NamingUnpack(const S: WideString): TWideStringArray;
begin
  if S='' then begin SetLength(Result,0); Exit; end;
  Result:=WideSplitString(WideCopy(S,1,WideLength(S)-1),#0);
end;
function MatchesRegEx(const S,P: WideString; Sensitive: Boolean): TWideStringArray;
begin Result:=NamingUnpack(NamingRegexList(S,P,Sensitive)); end;
function SubMatchesRegEx(const S,P: WideString; Sensitive: Boolean): TWideStringArray;
begin Result:=NamingUnpack(NamingRegexSubList(S,P,Sensitive)); end;
function FindRegEx(const S,P: WideString; Sensitive: Boolean; var Positions:TIntegerArray; var Matches:TWideStringArray):Integer;
var A:TWideStringArray; I:Integer;
begin
  Matches:=MatchesRegEx(S,P,Sensitive); A:=NamingUnpack(NamingRegexPositions(S,P,Sensitive));
  SetLength(Positions,Length(A)); for I:=0 to Length(A)-1 do Positions[I]:=StrToInt(A[I]);
  Result:=Length(Matches);
end;
function GetAllFiles:TWideStringArray; begin Result:=NamingUnpack(NamingAllFiles); end;
function GetMarkedFiles:TWideStringArray; begin Result:=NamingUnpack(NamingMarkedFiles); end;
function GetApplicationParams:TWideStringArray; begin Result:=NamingUnpack(NamingAppParams); end;
procedure WideScanDirForFiles(const Dir:WideString; var Files:TWideStringArray; Recursive,IncludeHidden,IncludeSystem:Boolean; const Mask:WideString);
begin Files:=NamingUnpack(NamingScanFiles(Dir,Mask,Recursive,IncludeHidden,IncludeSystem)); end;
procedure WideScanDirForFolders(const Dir:WideString; var Folders:TWideStringArray; Recursive,IncludeHidden,IncludeSystem:Boolean);
begin Folders:=NamingUnpack(NamingScanFolders(Dir,Recursive,IncludeHidden,IncludeSystem)); end;
function GetGlobalVarNames:TAnsiStringArray;
var A:TWideStringArray; I:Integer;
begin A:=NamingUnpack(NamingGlobalNames); SetLength(Result,Length(A));
  for I:=0 to Length(A)-1 do Result[I]:=UTF8Encode(A[I]); end;
