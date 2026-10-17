import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:toeigo/constants.dart';
import 'package:toeigo/core/api_client.dart';
import 'package:toeigo/services/route_search_service.dart';

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
    expect(candidate.steps.first.kind,'walk');
    final rail=candidate.steps.firstWhere((s)=>s.kind=='rail');
    expect(rail.tripId,startsWith('sendai_subway:'));
    expect(rail.routeId,startsWith('sendai_subway:'));
    expect(rail.planningDetails!['arrival']['basis'],'published_clock_arrival_proxy');
    expect(candidate.planningJourney!['actual_connection_guaranteed'],isFalse);
    expect(result.fareByCandidateId[candidate.id]!.normalFareYen,isNull);
    expect(result.fareByCandidateId[candidate.id]!.payNowYen,0);
    expect(rail.toJson()['planning_details'],rail.planningDetails);
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
