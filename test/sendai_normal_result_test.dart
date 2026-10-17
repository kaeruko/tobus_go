import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:toeigo/constants.dart';
import 'package:toeigo/core/api_client.dart';
import 'package:toeigo/services/route_search_service.dart';
import 'package:toeigo/models/route_models.dart';
import 'package:toeigo/widgets/route_detail_widgets.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final source=File('test/fixtures/sendai_normal_result.json').readAsStringSync();
  late http.Client original;
  setUp(() {original=ApiClient.httpClient;configureApiBase(Uri.parse('https://api.example.test'));});
  tearDown(() {ApiClient.httpClient=original;});
  RouteSearchRequest request()=>RouteSearchRequest(origin:const LatLng(38.259327,140.880753),
    destination:const LatLng(38.390049,140.720145),originName:'仙台駅前',destinationName:'泉岳自然ふれあい館',
    startTime:DateTime(2026,11,19,9),preference:'shortTime',farePolicyId:'sendai_fureai_pass',
    acceptExperimentalTransferModel:true);

  test('Sendai preserves concrete identity, clock provenance, fare and event order without Tokyo resolver',()async{
    final paths=<String>[];
    ApiClient.httpClient=MockClient((call)async{
      paths.add(call.url.path);
      expect(call.url.path,'/route');
      final body=jsonDecode(call.body) as Map;
      expect(body['fare_policy_id'],'sendai_fureai_pass');
      expect(body['accept_experimental_transfer_model'],isTrue);
      return http.Response(source,200,headers:{'content-type':'application/json; charset=utf-8'});
    });
    final result=await const ApiRouteSearchService(cityKey:'sendai').search(request());
    expect(paths,['/route']);
    final candidate=result.candidates.single;
    expect(candidate.arrivalTime,'10:48');
    expect(candidate.sendaiPlanningDeparture,DateTime(2026,11,19,9));
    expect(candidate.steps.first.kind,'walk');
    final rail=candidate.steps.firstWhere((s)=>s.kind=='rail');
    expect(rail.tripId,startsWith('sendai_subway:'));
    expect(rail.routeId,startsWith('sendai_subway:'));
    expect(rail.planningDetails!['arrival']['basis'],'published_clock_arrival_proxy');
    expect(candidate.planningJourney!['actual_connection_guaranteed'],isFalse);
    expect(result.fareByCandidateId[candidate.id]!.normalFareYen,isNull);
    expect(result.fareByCandidateId[candidate.id]!.payNowYen,0);
    expect(rail.toJson()['planning_details'],rail.planningDetails);
    final bus=candidate.steps.firstWhere((s)=>s.kind=='bus');
    expect(routeStepTimetableReferenceTime(candidate,bus),DateTime(2026,11,19,10,10));
  });

  test('Sendai civil clocks survive midnight and device timezone independently of the instant',(){
    // Synthetic wire-contract boundary only; this is not a claimed real trip
    // or a replacement for any frozen real-data OD or expected arrival.
    final value=Map<String,dynamic>.from((jsonDecode(source) as Map)['candidates'][0]);
    value['departure_date']='2026-11-19T00:05:00+09:00';
    final bus=(value['steps'] as List).firstWhere((s)=>s['kind']=='bus');
    bus['departure_time']='00:10';
    bus['planning_details']['departure']['date']='2026-11-20';
    bus['planning_details']['departure']['time']='00:10';
    bus['planning_details']['departure']['minute']={'numerator':10,'denominator':1};
    final candidate=Candidate.fromJson(value);
    expect(candidate.departureDate,DateTime.utc(2026,11,18,15,5));
    expect(candidate.sendaiPlanningDeparture,DateTime(2026,11,19,0,5));
    final segment=candidate.steps.firstWhere((s)=>s.kind=='bus');
    expect(routeStepTimetableReferenceTime(candidate,segment),DateTime(2026,11,20,0,10));
    segment.planningDetails!.remove('departure');
    expect(()=>routeStepTimetableReferenceTime(candidate,segment),throwsStateError);
  });

  test('Sendai rejects loss of published/estimated clock distinction',()async{
    final value=jsonDecode(source) as Map<String,dynamic>;
    final rail=(value['candidates'][0]['steps'] as List).firstWhere((s)=>s['kind']=='rail');
    rail.remove('planning_details');
    ApiClient.httpClient=MockClient((call)async=>http.Response(jsonEncode(value),200,
      headers:{'content-type':'application/json; charset=utf-8'}));
    await expectLater(const ApiRouteSearchService(cityKey:'sendai').search(request()),throwsFormatException);
  });
}
