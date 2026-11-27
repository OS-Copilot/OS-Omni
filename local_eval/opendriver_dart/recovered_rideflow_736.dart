import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../../app/app_state.dart';
import '../../../features/map/domain/map_adapter.dart';
import '../../../shared/models/models.dart';
import '../../../shared/theme/app_theme.dart';
import '../../../shared/utils/invoice_pdf.dart';
import '../../../shared/utils/ride_math.dart';
import '../../../shared/widgets/app_widgets.dart';

const _offlineGazetteer = <LocationPoint>[
  LocationPoint(
    id: 'la_civic_center',
    cityId: 'los_angeles',
    address: 'Los Angeles Civic Center, Los Angeles, CA',
    latitude: 34.0549,
    longitude: -118.2439,
  ),
  LocationPoint(
    id: 'la_city_hall',
    cityId: 'los_angeles',
    address: 'Los Angeles City Hall, Los Angeles, CA',
    latitude: 34.0537,
    longitude: -118.2428,
  ),
  LocationPoint(
    id: 'usc',
    cityId: 'los_angeles',
    address: 'University of Southern California, Los Angeles, CA',
    latitude: 34.0224,
    longitude: -118.2851,
  ),
  LocationPoint(
    id: 'san_diego_civic_center',
    cityId: 'san_diego',
    address: 'San Diego Civic Center, San Diego, CA',
    latitude: 32.7174,
    longitude: -117.1628,
  ),
  LocationPoint(
    id: 'san_diego_convention_center',
    cityId: 'san_diego',
    address: 'San Diego Convention Center, San Diego, CA',
    latitude: 32.7066,
    longitude: -117.1613,
  ),
  LocationPoint(
    id: 'petco_park',
    cityId: 'san_diego',
    address: 'Petco Park, San Diego, CA',
    latitude: 32.7073,
    longitude: -117.1573,
  ),
  LocationPoint(
    id: 'san_jose_city_hall',
    cityId: 'san_jose',
    address: 'San Jose City Hall, San Jose, CA',
    latitude: 37.3377,
    longitude: -121.8863,
  ),
  LocationPoint(
    id: 'san_jose_convention_center',
    cityId: 'san_jose',
    address: 'San Jose McEnery Convention Center, San Jose, CA',
    latitude: 37.3306,
    longitude: -121.8880,
  ),
  LocationPoint(
    id: 'winchester_mystery_house',
    cityId: 'san_jose',
    address: 'Winchester Mystery House, San Jose, CA',
    latitude: 37.3184,
    longitude: -121.9500,
  ),
  LocationPoint(
    id: 'houston_city_hall',
    cityId: 'houston',
    address: 'Houston City Hall, Houston, TX',
    latitude: 29.7600,
    longitude: -95.3694,
  ),
  LocationPoint(
    id: 'george_r_brown',
    cityId: 'houston',
    address: 'George R. Brown Convention Center, Houston, TX',
    latitude: 29.7522,
    longitude: -95.3579,
  ),
  LocationPoint(
    id: 'university_houston',
    cityId: 'houston',
    address: 'University of Houston, Houston, TX',
    latitude: 29.7199,
    longitude: -95.3422,
  ),
  LocationPoint(
    id: 'san_antonio_city_hall',
    cityId: 'san_antonio',
    address: 'San Antonio City Hall, San Antonio, TX',
    latitude: 29.4246,
    longitude: -98.4951,
  ),
  LocationPoint(
    id: 'san_antonio_convention_center',
    cityId: 'san_antonio',
    address: 'Henry B. Gonzalez Convention Center, San Antonio, TX',
    latitude: 29.4210,
    longitude: -98.4836,
  ),
  LocationPoint(
    id: 'san_antonio_market_square',
    cityId: 'san_antonio',
    address: 'Historic Market Square, San Antonio, TX',
    latitude: 29.4247,
    longitude: -98.5010,
  ),
  LocationPoint(
    id: 'dallas_city_hall',
    cityId: 'dallas',
    address: 'Dallas City Hall, Dallas, TX',
    latitude: 32.7765,
    longitude: -96.7970,
  ),
  LocationPoint(
    id: 'kay_bailey_hutchison',
    cityId: 'dallas',
    address: 'Kay Bailey Hutchison Convention Center, Dallas, TX',
    latitude: 32.7758,
    longitude: -96.8001,
  ),
  LocationPoint(
    id: 'smu',
    cityId: 'dallas',
    address: 'Southern Methodist University, Dallas, TX',
    latitude: 32.8412,
    longitude: -96.7845,
  ),
  LocationPoint(
    id: 'boston_city_hall',
    cityId: 'boston',
    address: 'Boston City Hall, Boston, MA',
    latitude: 42.3604,
    longitude: -71.0578,
  ),
  LocationPoint(
    id: 'boston_common',
    cityId: 'boston',
    address: 'Boston Common, Boston, MA',
    latitude: 42.3554,
    longitude: -71.0656,
  ),
  LocationPoint(
    id: 'mit',
    cityId: 'boston',
    address: 'MIT, Cambridge, MA',
    latitude: 42.3601,
    longitude: -71.0942,
  ),
  LocationPoint(
    id: 'worcester_city_hall',
    cityId: 'worcester',
    address: 'Worcester City Hall, Worcester, MA',
    latitude: 42.2626,
    longitude: -71.8023,
  ),
  LocationPoint(
    id: 'worcester_common',
    cityId: 'worcester',
    address: 'Worcester Common, Worcester, MA',
    latitude: 42.2620,
    longitude: -71.8014,
  ),
  LocationPoint(
    id: 'clark_university',
    cityId: 'worcester',
    address: 'Clark University, Worcester, MA',
    latitude: 42.2516,
    longitude: -71.8231,
  ),
  LocationPoint(
    id: 'springfield_city_hall',
    cityId: 'springfield_ma',
    address: 'Springfield City Hall, Springfield, MA',
    latitude: 42.1015,
    longitude: -72.5898,
  ),
  LocationPoint(
    id: 'springfield_massmutual_center',
    cityId: 'springfield_ma',
    address: 'MassMutual Center, Springfield, MA',
    latitude: 42.1012,
    longitude: -72.5892,
  ),
  LocationPoint(
    id: 'western_new_england_university',
    cityId: 'springfield_ma',
    address: 'Western New England University, Springfield, MA',
    latitude: 42.1155,
    longitude: -72.5198,
  ),
  LocationPoint(
    id: 'nyc_city_hall',
    cityId: 'new_york',
    address: 'New York City Hall, New York, NY',
    latitude: 40.7128,
    longitude: -74.0060,
  ),
  LocationPoint(
    id: 'world_trade_center',
    cityId: 'new_york',
    address: 'World Trade Center, New York, NY',
    latitude: 40.7127,
    longitude: -74.0134,
  ),
  LocationPoint(
    id: 'columbia_university',
    cityId: 'new_york',
    address: 'Columbia University, New York, NY',
    latitude: 40.8075,
    longitude: -73.9626,
  ),
  LocationPoint(
    id: 'buffalo_city_hall',
    cityId: 'buffalo',
    address: 'Buffalo City Hall, Buffalo, NY',
    latitude: 42.8864,
    longitude: -78.8790,
  ),
  LocationPoint(
    id: 'sahlen_field',
    cityId: 'buffalo',
    address: 'Sahlen Field, Buffalo, NY',
    latitude: 42.8811,
    longitude: -78.8736,
  ),
  LocationPoint(
    id: 'buffalo_state',
    cityId: 'buffalo',
    address: 'Buffalo State University, Buffalo, NY',
    latitude: 42.9336,
    longitude: -78.8830,
  ),
  LocationPoint(
    id: 'rochester_city_hall',
    cityId: 'rochester_ny',
    address: 'Rochester City Hall, Rochester, NY',
    latitude: 43.1566,
    longitude: -77.6152,
  ),
  LocationPoint(
    id: 'blue_cross_arena',
    cityId: 'rochester_ny',
    address: 'Blue Cross Arena, Rochester, NY',
    latitude: 43.1538,
    longitude: -77.6108,
  ),
  LocationPoint(
    id: 'eastman_school_music',
    cityId: 'rochester_ny',
    address: 'Eastman School of Music, Rochester, NY',
    latitude: 43.1577,
    longitude: -77.6016,
  ),
  LocationPoint(
    id: 'detroit_city_hall',
    cityId: 'detroit',
    address: 'Detroit City Hall, Detroit, MI',
    latitude: 42.3314,
    longitude: -83.0458,
  ),
  LocationPoint(
    id: 'huntington_place',
    cityId: 'detroit',
    address: 'Huntington Place Convention Center, Detroit, MI',
    latitude: 42.3266,
    longitude: -83.0494,
  ),
  LocationPoint(
    id: 'fox_theatre_detroit',
    cityId: 'detroit',
    address: 'Fox Theatre, Detroit, MI',
    latitude: 42.3382,
    longitude: -83.0524,
  ),
  LocationPoint(
    id: 'grand_rapids_city_hall',
    cityId: 'grand_rapids',
    address: 'Grand Rapids City Hall, Grand Rapids, MI',
    latitude: 42.9634,
    longitude: -85.6681,
  ),
  LocationPoint(
    id: 'devos_place',
    cityId: 'grand_rapids',
    address: 'DeVos Place, Grand Rapids, MI',
    latitude: 42.9681,
    longitude: -85.6727,
  ),
  LocationPoint(
    id: 'meyer_may_house',
    cityId: 'grand_rapids',
    address: 'Meyer May House, Grand Rapids, MI',
    latitude: 42.9533,
    longitude: -85.6591,
  ),
  LocationPoint(
    id: 'warren_city_center',
    cityId: 'warren_mi',
    address: 'Warren City Center, Warren, MI',
    latitude: 42.5145,
    longitude: -83.0147,
  ),
  LocationPoint(
    id: 'warren_community_center',
    cityId: 'warren_mi',
    address: 'Warren Community Center, Warren, MI',
    latitude: 42.5149,
    longitude: -83.0278,
  ),
  LocationPoint(
    id: 'red_oaks_waterpark',
    cityId: 'warren_mi',
    address: 'Red Oaks Waterpark, Madison Heights, MI',
    latitude: 42.5030,
    longitude: -83.1063,
  ),
  LocationPoint(
    id: 'seattle_city_hall',
    cityId: 'seattle',
    address: 'Seattle City Hall, Seattle, WA',
    latitude: 47.6038,
    longitude: -122.3301,
  ),
  LocationPoint(
    id: 'seattle_center',
    cityId: 'seattle',
    address: 'Seattle Center, Seattle, WA',
    latitude: 47.6219,
    longitude: -122.3517,
  ),
  LocationPoint(
    id: 'space_needle',
    cityId: 'seattle',
    address: 'Space Needle, Seattle, WA',
    latitude: 47.6205,
    longitude: -122.3493,
  ),
  LocationPoint(
    id: 'spokane_city_hall',
    cityId: 'spokane',
    address: 'Spokane City Hall, Spokane, WA',
    latitude: 47.6588,
    longitude: -117.4260,
  ),
  LocationPoint(
    id: 'spokane_convention_center',
    cityId: 'spokane',
    address: 'Spokane Convention Center, Spokane, WA',
    latitude: 47.6602,
    longitude: -117.4131,
  ),
  LocationPoint(
    id: 'manito_park',
    cityId: 'spokane',
    address: 'Manito Park, Spokane, WA',
    latitude: 47.6360,
    longitude: -117.4084,
  ),
  LocationPoint(
    id: 'tacoma_city_hall',
    cityId: 'tacoma',
    address: 'Tacoma City Hall, Tacoma, WA',
    latitude: 47.2530,
    longitude: -122.4443,
  ),
  LocationPoint(
    id: 'greater_tacoma_convention_center',
    cityId: 'tacoma',
    address: 'Greater Tacoma Convention Center, Tacoma, WA',
    latitude: 47.2484,
    longitude: -122.4382,
  ),
  LocationPoint(
    id: 'museum_of_glass',
    cityId: 'tacoma',
    address: 'Museum of Glass, Tacoma, WA',
    latitude: 47.2454,
    longitude: -122.4330,
  ),
];

class RiderHomeScreen extends StatefulWidget {
  const RiderHomeScreen({super.key});

  @override
  State<RiderHomeScreen> createState() => _RiderHomeScreenState();
}

class _RiderHomeScreenState extends State<RiderHomeScreen> {
  final _pickup = TextEditingController();
  final _destination = TextEditingController();
  final _waypointControllers = <TextEditingController>[];
  final _promo = TextEditingController();
  final _supportMessage = TextEditingController(
    text: 'I need help with my ride.',
  );
  final _map = const ServiceMapAdapter();

  int _section = 0;
  String _editingStop = 'destination';
  String _rideTier = 'standard';
  String _paymentMethod = 'card_on_file';
  String _supportCategory = 'safety concern';
  DateTime? _scheduledFor;
  LocationPoint? _pickupPoint;
  LocationPoint? _destinationPoint;
  final _waypointPoints = <LocationPoint?>[];
  LocationPoint? _mapFocusLocation;
  String? _appliedCityId;
  bool _mobileSheetOpen = false;

  @override
  void dispose() {
    _pickup.dispose();
    _destination.dispose();
    for (final controller in _waypointControllers) {
      controller.dispose();
    }
    _promo.dispose();
    _supportMessage.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    _applySelectedCityDefaults(state);
    final activeRide = state.activeRide;
    final pickup = _pickupPoint ?? _resolve(_pickup.text, state, 0);
    final destination = _selectedDestination(state);
    final waypoints = _selectedWaypoints(state);
    final size = MediaQuery.sizeOf(context);
    final isDesktop = size.width >= 900;
    final mobileSheetTop = (size.height * 0.22).clamp(176.0, 220.0).toDouble();

    return Scaffold(
      body: SafeArea(
        child: Stack(
          children: [
            _map.buildMap(
              pickup: pickup,
              destination: destination,
              waypoints: waypoints,
              currentLocation: state.currentLocation,
              serviceCenter: state.selectedCity?.centerLocation,
              ride: activeRide,
              fullBleed: true,
              tapTargetLabel: _editingStopTitle(_editingStop).toLowerCase(),
              onMapTap: _setFocusedLocationFromMap,
              focusLocation: _mapFocusLocation,
            ),
            Positioned(
              left: 20,
              top: 20,
              right: isDesktop ? null : 20,
              child: _TopBar(
                userName: state.currentUser?.name ?? 'Rider',
                compact: !isDesktop,
                onAccount: isDesktop
                    ? () => setState(() => _section = 4)
                    : () => _openMobileSection(4),
                onRefresh: state.refreshRider,
                onLogout: state.logout,
              ),
            ),
            if (isDesktop)
              Positioned(
                left: 20,
                top: 100,
                bottom: 20,
                width: 430,
                child: SingleChildScrollView(
                  child: _PanelShell(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _RiderTabs(section: _section, onChanged: _setSection),
                        const SizedBox(height: 16),
                        if (state.errorMessage != null) ...[
                          ErrorBanner(state.errorMessage!),
                          const SizedBox(height: 12),
                        ],
                        _sectionContent(state, activeRide),
                      ],
                    ),
                  ),
                ),
              )
            else ...[
              Positioned(
                left: 16,
                top: 92,
                right: 16,
                child: _MobileRideSearchBar(
                  pickup: pickup,
                  destination: destination,
                  activeRide: activeRide,
                  selectedCity: state.selectedCity,
                  onTap: () => _openMobileSection(0),
                ),
              ),
              if (!_mobileSheetOpen && state.errorMessage != null)
                Positioned(
                  left: 16,
                  top: 178,
                  right: 16,
                  child: ErrorBanner(state.errorMessage!),
                ),
              if (!_mobileSheetOpen)
                Positioned(
                  left: 14,
                  right: 14,
                  bottom: 14,
                  child: _MobileRiderNav(
                    section: _section,
                    onChanged: _openMobileSection,
                  ),
                ),
              if (_mobileSheetOpen)
                Positioned(
                  left: 0,
                  top: mobileSheetTop,
                  right: 0,
                  bottom: 0,
                  child: _MobileSheetShell(
                    title: _sectionTitle(_section),
                    onClose: _closeMobileSheet,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _RiderTabs(
                          section: _section,
                          onChanged: _openMobileSection,
                        ),
                        const SizedBox(height: 16),
                        if (state.errorMessage != null) ...[
                          ErrorBanner(state.errorMessage!),
                          const SizedBox(height: 12),
                        ],
                        _sectionContent(state, activeRide),
                      ],
                    ),
                  ),
                ),
            ],
            if (isDesktop && activeRide != null)
              Positioned(
                right: 20,
                top: 104,
                bottom: 20,
                width: 360,
                child: SingleChildScrollView(
                  child: _RightRail(activeRide: activeRide),
                ),
              ),
          ],
        ),
      ),
    );
  }

  void _setSection(int value) {
    setState(() => _section = value);
  }

  void _openMobileSection(int value) {
    setState(() {
      _section = value;
      _mobileSheetOpen = true;
    });
  }

  void _closeMobileSheet() {
    setState(() => _mobileSheetOpen = false);
  }

  Widget _sectionContent(AppState state, Ride? activeRide) {
    return switch (_section) {
      0 => _rideSection(state, activeRide),
      1 => _activeSection(state, activeRide),
      2 => _historySection(state),
      3 => _safetySection(state, activeRide),
      _ => _accountSection(state),
    };
  }

  String _sectionTitle(int section) {
    return switch (section) {
      0 => 'Plan ride',
      1 => 'Active ride',
      2 => 'Ride history',
      3 => 'Safety',
      _ => 'Account',
    };
  }

  Widget _rideSection(AppState state, Ride? activeRide) {
    final destination = _selectedDestination(state);
    final pickup = _pickupPoint ?? _resolve(_pickup.text, state, 0);
    final waypoints = _selectedWaypoints(state);
    final suggestions = _suggestions(state);
    final searchQuery = _editingController.text.trim();
    final hasResolvedEditingStop = _hasResolvedStop(_editingStop, state);
    final shouldShowSuggestions = !hasResolvedEditingStop &&
        (suggestions.isNotEmpty || searchQuery.length >= 3);
    if (state.paymentMethods.isNotEmpty &&
        !state.paymentMethods.any((method) => method.id == _paymentMethod)) {
      _paymentMethod = state.paymentMethods
          .firstWhere(
            (method) => method.isDefault,
            orElse: () => state.paymentMethods.first,
          )
          .id;
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'Where to?',
          style: Theme.of(
            context,
          ).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w900),
        ),
        const SizedBox(height: 12),
        _CitySelector(
          cities: state.serviceCities,
          selectedCity: state.selectedCity,
          onChanged: _changeCity,
        ),
        const SizedBox(height: 10),
        if (activeRide != null) ...[
          _ActiveNotice(ride: activeRide, onOpen: () => _setSection(1)),
          const SizedBox(height: 12),
        ],
        _LocationEditor(
          pickupController: _pickup,
          waypointControllers: _waypointControllers,
          destinationController: _destination,
          editingStop: _editingStop,
          onFocus: (stop) => setState(() => _editingStop = stop),
          onChanged: (stop, value) {
            setState(() {
              _editingStop = stop;
              if (stop == 'pickup') {
                _pickupPoint = null;
              } else if (stop == 'destination') {
                _destinationPoint = null;
              } else {
                final index = _waypointIndex(stop);
                if (index != null && index < _waypointPoints.length) {
                  _waypointPoints[index] = null;
                }
              }
            });
            state.clearFareEstimate();
          },
          onUseCurrentLocation: state.currentLocation == null
              ? null
              : () => _setLocation('pickup', state.currentLocation!),
          onAddWaypoint: _addWaypoint,
          onRemoveWaypoint: _removeWaypoint,
          onSwap: _swapLocations,
        ),
        if (shouldShowSuggestions) ...[
          const SizedBox(height: 12),
          _SuggestionsList(
            title: '${_editingStopTitle(_editingStop)} matches',
            suggestions: suggestions,
            isSearching: false,
            bias: _suggestionBias(state),
            onTap: (location) => _setLocation(_editingStop, location),
          ),
        ],
        if (destination != null) ...[
          const SizedBox(height: 12),
          _TripSummary(
            pickup: pickup,
            waypoints: waypoints,
            destination: destination,
            editingStop: _editingStop,
            canEditPins: activeRide?.isActive != true,
            onEditPickup: () => _startPinEdit('pickup'),
            onEditWaypoint: (index) => _startPinEdit('waypoint:$index'),
            onEditDestination: () => _startPinEdit('destination'),
          ),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: () => _saveCurrentDestination(state, destination),
              icon: const Icon(Icons.bookmark_add),
              label: const Text('Save destination'),
            ),
          ),
        ],
        if (destination == null && state.savedPlaces.isNotEmpty) ...[
          const SizedBox(height: 12),
          _SavedPlaces(
            places: state.savedPlaces,
            onPickup: (place) => _setLocation('pickup', place.location),
            onDestination: (place) =>
                _setLocation('destination', place.location),
          ),
        ],
        const SizedBox(height: 12),
        if (state.currentFare == null)
          _PreQuotePanel(
            canSeePrices: destination != null,
            isLoading: state.isLoading,
            hasActiveRide: activeRide?.isActive == true,
            paymentMethods: state.paymentMethods,
            selectedPaymentMethod: _paymentMethod,
            scheduledFor: _scheduledFor,
            onPaymentChanged: (value) => setState(() => _paymentMethod = value),
            onScheduleChanged: (value) => setState(() => _scheduledFor = value),
            onSeePrices: () => _estimateCurrentRide(state),
          )
        else
          _RideChooser(
            fare: state.currentFare!,
            options: state.rideOptions,
            selected: _rideTier,
            paymentMethods: state.paymentMethods,
            selectedPaymentMethod: _paymentMethod,
            promoController: _promo,
            scheduledFor: _scheduledFor,
            isLoading: state.isLoading,
            hasActiveRide: activeRide?.isActive == true,
            onRideChanged: (value) async {
              setState(() => _rideTier = value);
              await _estimateCurrentRide(state, rideTier: value);
            },
            onPaymentChanged: (value) async {
              setState(() => _paymentMethod = value);
              await _estimateCurrentRide(state);
            },
            onScheduleChanged: (value) async {
              setState(() => _scheduledFor = value);
              await _estimateCurrentRide(state);
            },
            onApplyPromo: () async {
              final ok = await state.validatePromo(_promo.text.trim());
              if (ok) await _estimateCurrentRide(state);
              return ok;
            },
            onClearPromo: () async {
              _promo.clear();
              await _estimateCurrentRide(state);
            },
            onRequest: () => _requestCurrentRide(state),
          ),
      ],
    );
  }

  Widget _activeSection(AppState state, Ride? activeRide) {
    final completed = state.latestCompletedRide;
    final cancelled = state.latestCancelledRide;
    if (activeRide != null) {
      return RiderActiveRidePanel(ride: activeRide);
    }
    if (cancelled != null) {
      return _CancelledRidePanel(
        ride: cancelled,
        onDismiss: state.dismissLatestCancelledRide,
        onRequestRide: _startAnotherRide,
      );
    }
    if (completed != null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ReceiptCard(ride: completed),
          const SizedBox(height: 12),
          FilledButton.tonalIcon(
            onPressed: () => _saveInvoicePdf(context, completed),
            icon: const Icon(Icons.picture_as_pdf),
            label: const Text('Save invoice PDF'),
          ),
          const SizedBox(height: 10),
          FilledButton.icon(
            onPressed: () => showDialog<void>(
              context: context,
              builder: (_) => RatingDialog(rideId: completed.id),
            ),
            icon: const Icon(Icons.star),
            label: const Text('Rate this trip'),
          ),
          const SizedBox(height: 10),
          FilledButton.icon(
            onPressed: _startAnotherRide,
            icon: const Icon(Icons.add_location_alt),
            label: const Text('Book another ride'),
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            onPressed: state.dismissLatestCompletedRide,
            icon: const Icon(Icons.check),
            label: const Text('Done'),
          ),
        ],
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const EmptyState('No active ride.'),
        const SizedBox(height: 12),
        FilledButton.icon(
          onPressed: _startAnotherRide,
          icon: const Icon(Icons.map),
          label: const Text('Request a ride'),
        ),
      ],
    );
  }

  Widget _historySection(AppState state) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Ride history', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 12),
        if (state.scheduledRides.isNotEmpty) ...[
          Text(
            'Scheduled rides',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          for (final ride in state.scheduledRides) ...[
            TripCard(ride: ride),
            const SizedBox(height: 10),
          ],
          const Divider(),
        ],
        if (state.rideHistory.isEmpty) const EmptyState('No rides yet.'),
        for (final ride in state.rideHistory.take(20)) ...[
          TripCard(ride: ride),
          if (ride.status == 'completed') ...[
            ReceiptCard(ride: ride),
            _RideRecordActions(ride: ride),
          ],
          const SizedBox(height: 12),
        ],
      ],
    );
  }

  Widget _safetySection(AppState state, Ride? activeRide) {
    const categories = [
      'safety concern',
      'driver issue',
      'lost item',
      'payment issue',
      'technical issue',
      'other',
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'Safety and support',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            ActionChip(
              avatar: const Icon(Icons.ios_share),
              label: const Text('Share trip'),
              onPressed: () => _showInfo(
                'Share trip',
                'A live trip share link was prepared for your trusted contact.',
              ),
            ),
            ActionChip(
              avatar: const Icon(Icons.emergency),
              label: const Text('Emergency help'),
              onPressed: () => _showInfo(
                'Emergency help',
                'Emergency support is available. In a real emergency, call local emergency services first.',
              ),
            ),
            ActionChip(
              avatar: const Icon(Icons.pin),
              label: const Text('Ride PIN'),
              onPressed: () => _showInfo(
                'Ride PIN',
                'Your ride PIN is 4821. Confirm it before starting the trip.',
              ),
            ),
          ],
        ),
        const SizedBox(height: 16),
        DropdownButtonFormField<String>(
          initialValue: _supportCategory,
          decoration: const InputDecoration(
            labelText: 'Category',
            border: OutlineInputBorder(),
          ),
          items: categories
              .map((item) => DropdownMenuItem(value: item, child: Text(item)))
              .toList(),
          onChanged: (value) =>
              setState(() => _supportCategory = value ?? _supportCategory),
        ),
        const SizedBox(height: 12),
        AppTextField(
          controller: _supportMessage,
          label: 'Message',
          minLines: 3,
          maxLines: 5,
        ),
        const SizedBox(height: 12),
        FilledButton.icon(
          onPressed: state.isLoading
              ? null
              : () => _submitSupportTicket(state, activeRide),
          icon: const Icon(Icons.support_agent),
          label: const Text('Create support ticket'),
        ),
        const SizedBox(height: 16),
        if (state.supportTickets.isEmpty)
          const EmptyState('No support tickets yet.'),
        for (final ticket in state.supportTickets)
          _SupportTicketRow(ticket: ticket),
      ],
    );
  }

  Widget _accountSection(AppState state) {
    final defaultPayment =
        state.paymentMethods.where((method) => method.isDefault).firstOrNull ??
            (state.paymentMethods.isEmpty ? null : state.paymentMethods.first);
    final completedTrips =
        state.rideHistory.where((ride) => ride.status == 'completed').length;
    final availableCoupons =
        state.coupons.where((coupon) => coupon['status'] == 'available').length;
    final paidPayments = state.paymentHistory
        .where((payment) => payment['status'] == 'paid')
        .length;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Account', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(state.currentUser?.name ?? ''),
                  Text(
                    state.currentUser?.email ?? '',
                    style: const TextStyle(color: AppColors.muted),
                  ),
                  if ((state.currentUser?.phone ?? '').isNotEmpty)
                    Text(
                      state.currentUser!.phone,
                      style: const TextStyle(color: AppColors.muted),
                    ),
                ],
              ),
            ),
            IconButton.filledTonal(
              tooltip: 'Edit profile',
              onPressed: () => showDialog<void>(
                context: context,
                builder: (_) => EditProfileDialog(user: state.currentUser),
              ),
              icon: const Icon(Icons.edit),
            ),
          ],
        ),
        const Divider(),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            _StatChip(icon: Icons.route, label: '$completedTrips trips'),
            _StatChip(
              icon: Icons.bookmark,
              label: '${state.savedPlaces.length} saved places',
            ),
            _StatChip(
              icon: Icons.local_offer,
              label: '$availableCoupons coupons',
            ),
          ],
        ),
        const SizedBox(height: 16),
        _AccountCard(
          title: 'Wallet',
          children: [
            Align(
              alignment: Alignment.centerLeft,
              child: FilledButton.tonalIcon(
                onPressed: () => showDialog<void>(
                  context: context,
                  builder: (_) => const AddPaymentMethodDialog(),
                ),
                icon: const Icon(Icons.add_card),
                label: const Text('Add card'),
              ),
            ),
            const SizedBox(height: 8),
            if (state.paymentMethods.isEmpty)
              const EmptyState('No active payment methods.')
            else
              for (final method in state.paymentMethods)
                _PaymentMethodRow(
                  method: method,
                  canDelete: state.paymentMethods.length > 1,
                ),
            const Divider(),
            _WalletRow(
              icon: Icons.credit_card,
              label: 'Payment methods',
              value: '${state.paymentMethods.length}',
            ),
            _WalletRow(
              icon: Icons.receipt_long,
              label: 'Paid trips',
              value: '$paidPayments',
            ),
            _WalletRow(
              icon: Icons.request_quote,
              label: 'Invoices',
              value: '${state.invoices.length}',
            ),
            _WalletRow(
              icon: Icons.replay,
              label: 'Refunds',
              value: '${state.refunds.length}',
            ),
            const Divider(),
            Text(
              'Default payment',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            Text(defaultPayment?.label ?? 'No active payment method'),
            const Divider(),
            Text(
              'Recent payments',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            if (state.paymentHistory.isEmpty)
              const EmptyState('No payments yet.')
            else
              for (final payment in state.paymentHistory.take(5))
                _MoneyMapRow(
                  icon: Icons.receipt_long,
                  title: payment['rideId'] as String? ?? 'Ride payment',
                  amount: (payment['amount'] as num?)?.toDouble() ?? 0,
                  status: payment['status'] as String? ?? '',
                  currencySymbol: payment['currencySymbol'] as String? ?? r'$',
                  currencyCode: payment['currencyCode'] as String? ?? 'USD',
                  currencyDecimals:
                      (payment['currencyDecimals'] as num?)?.toInt() ?? 2,
                ),
            if (state.invoices.isNotEmpty) ...[
              const Divider(),
              Text('Invoices', style: Theme.of(context).textTheme.titleMedium),
              for (final invoice in state.invoices.take(4))
                _PlainMapRow(
                  icon: Icons.request_quote,
                  title: invoice['id'] as String? ?? 'Invoice',
                  subtitle: invoice['status'] as String? ?? '',
                ),
            ],
            if (state.refunds.isNotEmpty) ...[
              const Divider(),
              Text('Refunds', style: Theme.of(context).textTheme.titleMedium),
              for (final refund in state.refunds.take(4))
                _MoneyMapRow(
                  icon: Icons.replay,
                  title: refund['reason'] as String? ?? 'Refund',
                  amount: (refund['amount'] as num?)?.toDouble() ?? 0,
                  status: refund['status'] as String? ?? '',
                  currencySymbol: refund['currencySymbol'] as String? ?? r'$',
                  currencyCode: refund['currencyCode'] as String? ?? 'USD',
                  currencyDecimals:
                      (refund['currencyDecimals'] as num?)?.toInt() ?? 2,
                ),
            ],
          ],
        ),
        const SizedBox(height: 16),
        _AccountCard(
          title: 'Coupons',
          children: [
            if (state.coupons.isEmpty) const EmptyState('No coupons yet.'),
            for (final coupon in state.coupons) _CouponRow(coupon: coupon),
          ],
        ),
        const SizedBox(height: 16),
        _AccountCard(
          title: 'Notifications',
          children: [
            if (state.notifications.isEmpty)
              const EmptyState('No notifications yet.'),
            for (final notification in state.notifications.take(8))
              _AccountNotificationRow(notification: notification),
            const Divider(),
            Text(
              'Refund progress',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            if (state.refunds.isEmpty)
              const EmptyState('No refund requests yet.'),
            for (final refund in state.refunds)
              _RefundProgressRow(refund: refund),
          ],
        ),
        const SizedBox(height: 16),
        _AccountCard(
          title: 'Saved places',
          children: [
            if (state.savedPlaces.isEmpty)
              const EmptyState('No saved places yet.'),
            for (final place in state.savedPlaces)
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.bookmark),
                title: Text(place.label),
                subtitle: Text(place.address),
                onTap: () => _useSavedPlaceAsDestination(state, place),
                trailing: IconButton(
                  tooltip: 'Delete saved place',
                  onPressed: () => state.deleteSavedPlace(place.id),
                  icon: const Icon(Icons.delete_outline),
                ),
              ),
          ],
        ),
      ],
    );
  }

  Future<void> _submitSupportTicket(AppState state, Ride? activeRide) async {
    final message = _supportMessage.text.trim();
    if (message.isEmpty) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('Please enter a message.')));
      return;
    }
    final ticket = await state.createSupportTicket(
      message,
      category: _supportCategory,
      rideId: activeRide?.id ?? '',
    );
    if (!mounted || ticket == null) return;
    setState(() {
      _supportMessage.text = 'I need help with my ride.';
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          'Support ticket ${ticket.id} created. Status: ${ticket.status}.',
        ),
      ),
    );
  }

  Future<void> _estimateCurrentRide(AppState state, {String? rideTier}) async {
    final destination = _selectedDestination(state);
    if (destination == null) {
      state.clearFareEstimate();
      return;
    }
    await state.estimateRide(
      _pickupPoint ?? _resolve(_pickup.text, state, 0),
      destination,
      waypoints: _selectedWaypoints(state),
      rideTier: rideTier ?? _rideTier,
      paymentMethod: _paymentMethod,
      promoCode: _promo.text.trim(),
      scheduledFor: _scheduledFor,
    );
  }

  Future<void> _requestCurrentRide(AppState state) async {
    final destination = _selectedDestination(state);
    if (destination == null) return;
    await state.requestRide(
      _pickupPoint ?? _resolve(_pickup.text, state, 0),
      destination,
      waypoints: _selectedWaypoints(state),
      rideTier: _rideTier,
      paymentMethod: _paymentMethod,
      promoCode: _promo.text.trim(),
      scheduledFor: _scheduledFor,
    );
    if (!mounted) return;
    setState(() => _section = _scheduledFor == null ? 1 : 2);
  }

  void _useSavedPlaceAsDestination(AppState state, SavedPlace place) {
    setState(() {
      _section = 0;
      _mobileSheetOpen = true;
    });
    _setLocation('destination', place.location);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('${place.label} set as destination')),
    );
  }

  void _startAnotherRide() {
    final state = context.read<AppState>();
    state.dismissLatestCompletedRide();
    final pickup = state.currentLocation ?? state.selectedCity?.centerLocation;
    setState(() {
      _section = 0;
      _destination.clear();
      _destinationPoint = null;
      _clearWaypoints();
      _promo.clear();
      _scheduledFor = null;
      _rideTier = 'standard';
      _mobileSheetOpen = true;
      if (pickup != null) {
        _pickup.text = pickup.address;
        _pickupPoint = pickup;
        _mapFocusLocation = pickup;
      }
      _editingStop = 'destination';
    });
    state.clearFareEstimate();
  }

  void _changeCity(ServiceCity city) {
    context.read<AppState>().setSelectedCity(city);
    setState(() => _appliedCityId = null);
  }

  void _applySelectedCityDefaults(AppState state) {
    final city = state.selectedCity;
    if (city == null || _appliedCityId == city.id) return;
    final pickup = state.currentLocation ?? city.centerLocation;
    _pickup.text = pickup.address;
    _destination.clear();
    _pickupPoint = pickup;
    _destinationPoint = null;
    _clearWaypoints(disposeControllers: false);
    _mapFocusLocation = pickup;
    _editingStop = 'destination';
    _appliedCityId = city.id;
  }

  LocationPoint? _selectedDestination(AppState state) {
    if (_destinationPoint != null) return _destinationPoint;
    if (_destination.text.trim().isEmpty) return null;
    final query = _destination.text.trim().toLowerCase();
    return _allSearchableLocations(state)
        .where((location) => location.address.toLowerCase() == query)
        .firstOrNull;
  }

  List<LocationPoint> _selectedWaypoints(AppState state) {
    final points = <LocationPoint>[];
    for (var index = 0; index < _waypointControllers.length; index += 1) {
      final point = _selectedWaypoint(index, state);
      if (point != null) points.add(point);
    }
    return points;
  }

  LocationPoint? _selectedWaypoint(int index, AppState state) {
    if (index < 0 || index >= _waypointControllers.length) return null;
    final saved =
        index < _waypointPoints.length ? _waypointPoints[index] : null;
    if (saved != null) return saved;
    final text = _waypointControllers[index].text.trim();
    if (text.isEmpty) return null;
    final query = text.toLowerCase();
    return _allSearchableLocations(state)
        .where((location) => location.address.toLowerCase() == query)
        .firstOrNull;
  }

  bool _hasResolvedStop(String stop, AppState state) {
    if (stop == 'pickup') return _pickupPoint != null;
    if (stop == 'destination') return _selectedDestination(state) != null;
    final index = _waypointIndex(stop);
    return index != null && _selectedWaypoint(index, state) != null;
  }

  TextEditingController get _editingController {
    final index = _waypointIndex(_editingStop);
    if (index != null && index < _waypointControllers.length) {
      return _waypointControllers[index];
    }
    return _editingStop == 'pickup' ? _pickup : _destination;
  }

  int? _waypointIndex(String stop) {
    if (!stop.startsWith('waypoint:')) return null;
    return int.tryParse(stop.substring('waypoint:'.length));
  }

  String _editingStopTitle(String stop) {
    if (stop == 'pickup') return 'Pickup';
    final index = _waypointIndex(stop);
    if (index != null) return 'Stop ${index + 1}';
    return 'Destination';
  }

  LocationPoint? _suggestionBias(AppState state) {
    if (_editingStop == 'pickup') return state.currentLocation;
    final index = _waypointIndex(_editingStop);
    if (index != null && index > 0) return _selectedWaypoint(index - 1, state);
    return _pickupPoint ?? state.currentLocation;
  }

  void _addWaypoint() {
    setState(() {
      _waypointControllers.add(TextEditingController());
      _waypointPoints.add(null);
      _editingStop = 'waypoint:${_waypointControllers.length - 1}';
    });
    context.read<AppState>().clearFareEstimate();
  }

  void _removeWaypoint(int index) {
    if (index < 0 || index >= _waypointControllers.length) return;
    setState(() {
      _waypointControllers.removeAt(index).dispose();
      if (index < _waypointPoints.length) _waypointPoints.removeAt(index);
      _editingStop = 'destination';
    });
    final state = context.read<AppState>();
    state.clearFareEstimate();
    if (_selectedDestination(state) != null && _pickup.text.trim().isNotEmpty) {
      unawaited(_estimateCurrentRide(state));
    }
  }

  void _clearWaypoints({bool disposeControllers = true}) {
    if (disposeControllers) {
      for (final controller in _waypointControllers) {
        controller.dispose();
      }
      _waypointControllers.clear();
    } else {
      for (final controller in _waypointControllers) {
        controller.clear();
      }
    }
    _waypointPoints.clear();
    _waypointPoints.addAll(
      List<LocationPoint?>.filled(_waypointControllers.length, null),
    );
  }

  LocationPoint _resolve(String value, AppState state, int index) {
    final current = state.currentLocation;
    if (current != null && value.trim() == current.address) return current;
    final query = value.trim().toLowerCase();
    final match = _allSearchableLocations(state)
        .where((location) => location.address.toLowerCase().contains(query))
        .firstOrNull;
    if (match != null) return match;
    final city = state.selectedCity;
    return LocationPoint(
      cityId: city?.id ?? '',
      address: value.trim().isEmpty
          ? '${city?.name ?? 'Service city'} manual location'
          : value.trim(),
      latitude: (city?.centerLatitude ?? 37.4477) + index * 0.03,
      longitude: (city?.centerLongitude ?? -122.1619) - index * 0.04,
    );
  }

  List<LocationPoint> _suggestions(AppState state) {
    final query = _editingController.text.trim().toLowerCase();
    final locations = _allLocations(state);
    final bias = _suggestionBias(state);
    if (query.isEmpty) {
      return _rankedLocations(locations, state, query, bias).take(5).toList();
    }
    final merged = <String, LocationPoint>{};
    for (final location in _keywordFallbacks(state, query)) {
      merged[_locationKey(location)] = location;
    }
    for (final location in _offlineGazetteerSuggestions(state, query)) {
      merged[_locationKey(location)] = location;
    }
    final matches = _allServiceLocations(
      state,
    ).where((location) => _matchesLocationQuery(location, query)).toList()
      ..sort((a, b) {
        final selectedId = state.selectedCity?.id ?? '';
        final aLocal = a.cityId == selectedId ? 0 : 1;
        final bLocal = b.cityId == selectedId ? 0 : 1;
        final localCompare = aLocal.compareTo(bLocal);
        if (localCompare != 0) return localCompare;
        return _locationScore(b, query).compareTo(_locationScore(a, query));
      });
    for (final city in state.serviceCities.where(
      (city) =>
          city.name.toLowerCase().contains(query) ||
          city.region.toLowerCase().contains(query) ||
          city.currencyCode.toLowerCase().contains(query),
    )) {
      final location = LocationPoint(
        id: city.centerLocation.id,
        cityId: city.id,
        address: '${city.name}, ${city.region} service area',
        latitude: city.centerLatitude,
        longitude: city.centerLongitude,
      );
      merged[_locationKey(location)] = location;
    }
    for (final location in matches) {
      merged[_locationKey(location)] = location;
    }
    return _rankedLocations(
      merged.values.toList(),
      state,
      query,
      bias,
    ).take(8).toList();
  }

  List<LocationPoint> _rankedLocations(
    List<LocationPoint> locations,
    AppState state,
    String query,
    LocationPoint? bias,
  ) {
    final selectedId = state.selectedCity?.id ?? '';
    return List<LocationPoint>.from(locations)
      ..sort((a, b) {
        final aScore = _locationScore(a, query);
        final bScore = _locationScore(b, query);
        final scoreDelta = bScore - aScore;
        if (scoreDelta.abs() >= 8) return scoreDelta;

        final aDistance = _distanceFromBiasKm(bias, a);
        final bDistance = _distanceFromBiasKm(bias, b);
        final distanceCompare = aDistance.compareTo(bDistance);
        if (distanceCompare != 0) return distanceCompare;

        final aLocal = a.cityId == selectedId ? 0 : 1;
        final bLocal = b.cityId == selectedId ? 0 : 1;
        final localCompare = aLocal.compareTo(bLocal);
        if (localCompare != 0) return localCompare;

        return scoreDelta;
      });
  }

  double _distanceFromBiasKm(LocationPoint? bias, LocationPoint location) {
    if (bias == null) return double.infinity;
    return calculateHaversineDistance(
      startLatitude: bias.latitude,
      startLongitude: bias.longitude,
      endLatitude: location.latitude,
      endLongitude: location.longitude,
    );
  }

  List<LocationPoint> _allServiceLocations(AppState state) {
    return [
      ...state.serviceCities.expand((city) => city.locations),
      ..._offlineGazetteerLocations(state),
    ];
  }

  List<LocationPoint> _allSearchableLocations(AppState state) {
    final deduped = <LocationPoint>[];
    for (final location in [
      ..._allLocations(state),
      ..._offlineGazetteerLocations(state),
    ]) {
      _addUniqueLocation(deduped, location);
    }
    return deduped;
  }

  ServiceCity? _cityForLocation(AppState state, LocationPoint location) {
    if (location.cityId.isNotEmpty) {
      return state.serviceCities
          .where((city) => city.id == location.cityId)
          .firstOrNull;
    }
    final candidates = state.serviceCities
        .map(
          (city) => (
            city: city,
            distance: calculateHaversineDistance(
              startLatitude: city.centerLatitude,
              startLongitude: city.centerLongitude,
              endLatitude: location.latitude,
              endLongitude: location.longitude,
            ),
          ),
        )
        .where((item) => item.distance <= item.city.radiusKm)
        .toList();
    candidates.sort((a, b) => a.distance.compareTo(b.distance));
    return candidates.firstOrNull?.city;
  }

  Future<bool> _confirmMarketSwitch(
    AppState state,
    ServiceCity market,
    LocationPoint location,
  ) async {
    final current = state.selectedCity;
    if (current == null || current.id == market.id) return true;
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text('Switch to ${market.name}?'),
        content: Text(
          '${location.address} is in the ${market.name}, ${market.region} service market. Switch markets and reset pickup to ${market.name} service area?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Switch market'),
          ),
        ],
      ),
    );
    if (ok != true) return false;
    state.setSelectedCity(market);
    setState(() {
      _appliedCityId = market.id;
      final pickup = market.centerLocation;
      _pickupPoint = pickup;
      _pickup.text = pickup.address;
      _mapFocusLocation = location;
    });
    return true;
  }

  String _locationKey(LocationPoint location) {
    return '${_normalizeLocationAddress(location.address)}_'
        '${location.latitude.toStringAsFixed(4)}_'
        '${location.longitude.toStringAsFixed(4)}';
  }

  bool _addUniqueLocation(List<LocationPoint> locations, LocationPoint next) {
    if (locations.any((location) => _sameSearchLocation(location, next))) {
      return false;
    }
    locations.add(next);
    return true;
  }

  bool _sameSearchLocation(LocationPoint a, LocationPoint b) {
    if (_locationKey(a) == _locationKey(b)) return true;
    final distance = calculateHaversineDistance(
      startLatitude: a.latitude,
      startLongitude: a.longitude,
      endLatitude: b.latitude,
      endLongitude: b.longitude,
    );
    if (distance > 0.08) return false;
    final aText = _normalizeLocationAddress(a.address);
    final bText = _normalizeLocationAddress(b.address);
    if (aText == bText || aText.contains(bText) || bText.contains(aText)) {
      return true;
    }
    final aTokens = aText.split(' ').where((token) => token.length > 2).toSet();
    final bTokens = bText.split(' ').where((token) => token.length > 2).toSet();
    if (aTokens.isEmpty || bTokens.isEmpty) return false;
    return aTokens.intersection(bTokens).length >= 2;
  }

  bool _matchesLocationQuery(LocationPoint location, String query) {
    final normalizedQuery = _normalizeLocationAddress(query);
    if (normalizedQuery.isEmpty) {
      return _locationAliases(
        location,
      ).any((alias) => query.toLowerCase().contains(alias.toLowerCase()));
    }
    final searchTexts = _locationSearchTexts(location);
    if (searchTexts.any((text) => text.contains(normalizedQuery))) {
      return true;
    }
    final queryTokens = normalizedQuery
        .split(' ')
        .where((token) => token.length > 1)
        .toList(growable: false);
    if (queryTokens.isEmpty) return false;
    return searchTexts.any(
      (text) => queryTokens.every((token) => text.contains(token)),
    );
  }

  int _locationScore(LocationPoint location, String query) {
    final normalizedQuery = _normalizeLocationAddress(query);
    var score = 0;
    for (final text in _locationSearchTexts(location)) {
      if (text.startsWith(normalizedQuery)) score += 8;
      if (text.contains(normalizedQuery)) score += 4;
      for (final token in normalizedQuery.split(' ')) {
        if (token.length > 1 && text.contains(token)) score += 1;
      }
    }
    return score;
  }

  List<String> _locationSearchTexts(LocationPoint location) {
    return [
      location.address,
      location.id.replaceAll('_', ' '),
      ..._locationAliases(location),
    ]
        .map(_normalizeLocationAddress)
        .where((text) => text.isNotEmpty)
        .toSet()
        .toList(growable: false);
  }

  List<String> _locationAliases(LocationPoint location) {
    final id = location.id.toLowerCase();
    final address = _normalizeLocationAddress(location.address);
    if (id == 'nyu' || address.contains('new york university')) {
      return const ['nyu', 'new york university', '纽约大学'];
    }
    return const [];
  }

  String _normalizeLocationAddress(String value) {
    return value
        .toLowerCase()
        .replaceAll('&', ' and ')
        .replaceAll(RegExp(r'[^a-z0-9]+'), ' ')
        .replaceAll(
          RegExp(
            r'\b(street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|suite|ste|floor|fl)\b',
          ),
          ' ',
        )
        .replaceAll(RegExp(r'\s+'), ' ')
        .trim();
  }

  List<LocationPoint> _keywordFallbacks(AppState state, String query) {
    final cityId = state.selectedCity?.id ?? '';
    final normalizedQuery = _normalizeLocationAddress(query);
    if (cityId == 'new_york' &&
        (normalizedQuery.contains('nyu') ||
            normalizedQuery.contains('new york university') ||
            query.toLowerCase().contains('纽约大学'))) {
      return const [
        LocationPoint(
          id: 'nyu',
          cityId: 'new_york',
          address: 'New York University, Greenwich Village, New York, NY',
          latitude: 40.7295,
          longitude: -73.9965,
        ),
      ];
    }
    if (cityId == 'sf_bay' && query.contains('zoom')) {
      return const [
        LocationPoint(
          cityId: 'sf_bay',
          address: 'Zoom Room Dog Training, 1412 El Camino Real, Belmont, CA',
          latitude: 37.5172,
          longitude: -122.2758,
        ),
        LocationPoint(
          cityId: 'sf_bay',
          address:
              'Zoom Video Communications, 55 Almaden Boulevard, San Jose, CA',
          latitude: 37.3322,
          longitude: -121.8911,
        ),
      ];
    }
    if (cityId == 'sf_bay' && query.contains('meta')) {
      return const [
        LocationPoint(
          cityId: 'sf_bay',
          address: 'Meta MPK 23, 300 Constitution Drive, Menlo Park, CA',
          latitude: 37.4803,
          longitude: -122.1669,
        ),
        LocationPoint(
          cityId: 'sf_bay',
          address: 'Meta Park, Menlo Park, California, United States',
          latitude: 37.4807,
          longitude: -122.1623,
        ),
        LocationPoint(
          cityId: 'sf_bay',
          address: 'Meta West Campus, Menlo Park, California, United States',
          latitude: 37.4813,
          longitude: -122.1592,
        ),
        LocationPoint(
          cityId: 'sf_bay',
          address: 'Meta MPK 20, 1 Meta Way, Menlo Park, California',
          latitude: 37.4810,
          longitude: -122.1542,
        ),
        LocationPoint(
          cityId: 'sf_bay',
          address: 'Meta MPK 22, 1 Meta Way, Menlo Park, California',
          latitude: 37.4819,
          longitude: -122.1636,
        ),
      ];
    }
    return const [];
  }

  List<LocationPoint> _offlineGazetteerSuggestions(
    AppState state,
    String query,
  ) {
    final matches = _offlineGazetteerLocations(
      state,
    ).where((location) => _matchesLocationQuery(location, query)).toList();
    final selectedId = state.selectedCity?.id ?? '';
    matches.sort((a, b) {
      final aLocal = a.cityId == selectedId ? 0 : 1;
      final bLocal = b.cityId == selectedId ? 0 : 1;
      final localCompare = aLocal.compareTo(bLocal);
      if (localCompare != 0) return localCompare;
      return _locationScore(b, query).compareTo(_locationScore(a, query));
    });
    return matches;
  }

  List<LocationPoint> _offlineGazetteerLocations(AppState state) {
    final enabledCityIds = state.serviceCities.map((city) => city.id).toSet();
    return _offlineGazetteer
        .where((location) => enabledCityIds.contains(location.cityId))
        .toList(growable: false);
  }

  List<LocationPoint> _allLocations(AppState state) {
    final city = state.selectedCity;
    final locations =
        city?.locations.isNotEmpty == true ? city!.locations : state.locations;
    final deduped = <LocationPoint>[];
    for (final location in [
      if (state.currentLocation != null) state.currentLocation!,
      ...locations,
    ]) {
      _addUniqueLocation(deduped, location);
    }
    return deduped;
  }

  void _setFocusedLocationFromMap(LocationPoint location) {
    final label = '${_editingStopTitle(_editingStop)} pin';
    _setLocation(
      _editingStop,
      LocationPoint(
        address:
            '$label, ${location.latitude.toStringAsFixed(5)}, ${location.longitude.toStringAsFixed(5)}',
        latitude: location.latitude,
        longitude: location.longitude,
      ),
    );
  }

  void _setLocation(String stop, LocationPoint location) {
    unawaited(_setLocationAfterMarketCheck(stop, location));
  }

  Future<void> _setLocationAfterMarketCheck(
    String stop,
    LocationPoint location,
  ) async {
    final state = context.read<AppState>();
    final market = _cityForLocation(state, location);
    if (market != null && market.id != state.selectedCity?.id) {
      final switched = await _confirmMarketSwitch(state, market, location);
      if (!switched || !mounted) return;
    }
    setState(() {
      _editingStop = stop;
      if (stop == 'pickup') {
        _pickupPoint = location;
        _pickup.text = location.address;
      } else if (stop == 'destination') {
        _destinationPoint = location;
        _destination.text = location.address;
      } else {
        final index = _waypointIndex(stop);
        if (index != null && index < _waypointControllers.length) {
          _waypointPoints[index] = location;
          _waypointControllers[index].text = location.address;
        }
      }
      _mapFocusLocation = location;
    });
    state.clearFareEstimate();
    if (_selectedDestination(state) != null && _pickup.text.trim().isNotEmpty) {
      unawaited(_estimateCurrentRide(state));
    }
  }

  void _startPinEdit(String stop) {
    setState(() {
      _editingStop = stop;
      _mobileSheetOpen = false;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          stop == 'pickup'
              ? 'Tap the map to move the pickup pin.'
              : 'Tap the map to move the ${_editingStopTitle(stop).toLowerCase()} pin.',
        ),
      ),
    );
  }

  void _swapLocations() {
    if (_destination.text.trim().isEmpty && _destinationPoint == null) return;
    setState(() {
      final pickupText = _pickup.text;
      final pickupPoint = _pickupPoint;
      _pickup.text = _destination.text;
      _pickupPoint = _destinationPoint;
      _destination.text = pickupText;
      _destinationPoint = pickupPoint;
      final waypointTexts =
          _waypointControllers.map((controller) => controller.text).toList();
      final waypointPoints = List<LocationPoint?>.from(_waypointPoints);
      for (var index = 0; index < _waypointControllers.length; index += 1) {
        _waypointControllers[index].text =
            waypointTexts[waypointTexts.length - index - 1];
        _waypointPoints[index] =
            waypointPoints[waypointPoints.length - index - 1];
      }
      _editingStop = 'destination';
      _mapFocusLocation = _pickupPoint;
    });
    context.read<AppState>().clearFareEstimate();
  }

  Future<void> _saveCurrentDestination(
    AppState state,
    LocationPoint destination,
  ) async {
    final label = await showDialog<String>(
      context: context,
      builder: (_) => _SavePlaceDialog(defaultLabel: destination.address),
    );
    if (label == null || label.trim().isEmpty) return;
    await state.savePlace(label.trim(), destination);
  }

  void _showInfo(String title, String message) {
    showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }
}

class _TopBar extends StatelessWidget {
  const _TopBar({
    required this.userName,
    required this.onAccount,
    required this.onRefresh,
    required this.onLogout,
    this.compact = false,
  });

  final String userName;
  final VoidCallback onAccount;
  final VoidCallback onRefresh;
  final VoidCallback onLogout;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.95),
        borderRadius: BorderRadius.circular(18),
        boxShadow: const [
          BoxShadow(
            color: Color(0x22000000),
            blurRadius: 14,
            offset: Offset(0, 4),
          ),
        ],
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.local_taxi, color: AppColors.accent),
            const SizedBox(width: 8),
            Text(
              'opendriver',
              style: Theme.of(
                context,
              ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w900),
            ),
            const SizedBox(width: 10),
            if (compact)
              IconButton(
                tooltip: 'Account',
                onPressed: onAccount,
                icon: const Icon(Icons.person),
              )
            else
              TextButton.icon(
                onPressed: onAccount,
                icon: const Icon(Icons.person, size: 18),
                label: const Text('Account'),
              ),
            IconButton(
              tooltip: 'Refresh',
              onPressed: onRefresh,
              icon: const Icon(Icons.refresh),
            ),
            IconButton(
              tooltip: 'Logout',
              onPressed: onLogout,
              icon: const Icon(Icons.logout),
            ),
          ],
        ),
      ),
    );
  }
}

class _MobileRideSearchBar extends StatelessWidget {
  const _MobileRideSearchBar({
    required this.pickup,
    required this.destination,
    required this.activeRide,
    required this.selectedCity,
    required this.onTap,
  });

  final LocationPoint pickup;
  final LocationPoint? destination;
  final Ride? activeRide;
  final ServiceCity? selectedCity;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final ride = activeRide;
    final title = ride?.isActive == true
        ? 'Track current ride'
        : destination?.address ?? 'Where to?';
    final subtitle = ride?.isActive == true
        ? ride!.destinationAddress
        : destination == null
            ? selectedCity == null
                ? 'Search destination'
                : '${selectedCity!.name}, ${selectedCity!.region}'
            : 'Pickup: ${pickup.address}';
    return Material(
      color: Colors.white.withValues(alpha: 0.97),
      elevation: 10,
      shadowColor: Colors.black.withValues(alpha: 0.18),
      borderRadius: BorderRadius.circular(22),
      child: InkWell(
        borderRadius: BorderRadius.circular(22),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
          child: Row(
            children: [
              Container(
                width: 42,
                height: 42,
                decoration: BoxDecoration(
                  color: AppColors.accent.withValues(alpha: 0.12),
                  shape: BoxShape.circle,
                ),
                child: Icon(
                  ride?.isActive == true ? Icons.route : Icons.search,
                  color: AppColors.accent,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w900,
                          ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      subtitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: AppColors.muted,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              const Icon(Icons.keyboard_arrow_up, color: AppColors.muted),
            ],
          ),
        ),
      ),
    );
  }
}

class _MobileRiderNav extends StatelessWidget {
  const _MobileRiderNav({required this.section, required this.onChanged});

  final int section;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white.withValues(alpha: 0.97),
      elevation: 10,
      shadowColor: Colors.black.withValues(alpha: 0.18),
      borderRadius: BorderRadius.circular(24),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(24),
        child: NavigationBar(
          height: 72,
          selectedIndex: section,
          backgroundColor: Colors.transparent,
          indicatorColor: AppColors.accent.withValues(alpha: 0.14),
          labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
          onDestinationSelected: onChanged,
          destinations: const [
            NavigationDestination(icon: Icon(Icons.map), label: 'Ride'),
            NavigationDestination(icon: Icon(Icons.timeline), label: 'Active'),
            NavigationDestination(icon: Icon(Icons.history), label: 'History'),
            NavigationDestination(
              icon: Icon(Icons.health_and_safety),
              label: 'Safety',
            ),
            NavigationDestination(icon: Icon(Icons.person), label: 'Account'),
          ],
        ),
      ),
    );
  }
}

class _MobileSheetShell extends StatelessWidget {
  const _MobileSheetShell({
    required this.title,
    required this.onClose,
    required this.child,
  });

  final String title;
  final VoidCallback onClose;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
        boxShadow: [
          BoxShadow(
            color: Color(0x33000000),
            blurRadius: 26,
            offset: Offset(0, -8),
          ),
        ],
      ),
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 10, 10, 4),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Center(
                        child: Container(
                          width: 42,
                          height: 4,
                          decoration: BoxDecoration(
                            color: Colors.black.withValues(alpha: 0.18),
                            borderRadius: BorderRadius.circular(999),
                          ),
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        title,
                        style: Theme.of(context)
                            .textTheme
                            .titleMedium
                            ?.copyWith(fontWeight: FontWeight.w900),
                      ),
                    ],
                  ),
                ),
                IconButton(
                  tooltip: 'Close',
                  onPressed: onClose,
                  icon: const Icon(Icons.close),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 28),
              child: child,
            ),
          ),
        ],
      ),
    );
  }
}

class _PanelShell extends StatelessWidget {
  const _PanelShell({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.97),
        borderRadius: BorderRadius.circular(22),
        boxShadow: const [
          BoxShadow(
            color: Color(0x24000000),
            blurRadius: 22,
            offset: Offset(0, 8),
          ),
        ],
      ),
      child: Padding(padding: const EdgeInsets.all(18), child: child),
    );
  }
}

class _RiderTabs extends StatelessWidget {
  const _RiderTabs({required this.section, required this.onChanged});

  final int section;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    const tabs = [
      (0, Icons.map, 'Ride'),
      (1, Icons.timeline, 'Active'),
      (2, Icons.history, 'History'),
      (3, Icons.health_and_safety, 'Safety'),
      (4, Icons.person, 'Account'),
    ];
    const tabTextStyle = TextStyle(
      fontSize: 13,
      height: 1,
      fontWeight: FontWeight.w900,
      letterSpacing: 0,
    );
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: Colors.black.withValues(alpha: 0.12)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(4),
        child: Row(
          children: [
            for (final tab in tabs)
              Expanded(
                child: InkWell(
                  borderRadius: BorderRadius.circular(999),
                  onTap: () => onChanged(tab.$1),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 140),
                    height: 44,
                    padding: const EdgeInsets.symmetric(horizontal: 1),
                    decoration: BoxDecoration(
                      color: section == tab.$1
                          ? AppColors.accent.withValues(alpha: 0.14)
                          : Colors.transparent,
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(
                          tab.$2,
                          size: 16,
                          color: section == tab.$1
                              ? AppColors.accent
                              : AppColors.ink,
                        ),
                        const SizedBox(width: 3),
                        Flexible(
                          child: Text(
                            tab.$3,
                            maxLines: 1,
                            overflow: TextOverflow.visible,
                            textAlign: TextAlign.center,
                            style: tabTextStyle.copyWith(
                              color: section == tab.$1
                                  ? AppColors.accent
                                  : AppColors.ink,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _CitySelector extends StatelessWidget {
  const _CitySelector({
    required this.cities,
    required this.selectedCity,
    required this.onChanged,
  });

  final List<ServiceCity> cities;
  final ServiceCity? selectedCity;
  final ValueChanged<ServiceCity> onChanged;

  @override
  Widget build(BuildContext context) {
    final city = selectedCity;
    return OutlinedButton(
      style: OutlinedButton.styleFrom(
        foregroundColor: AppColors.ink,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        side: BorderSide(color: Colors.black.withValues(alpha: 0.22)),
      ),
      onPressed: () async {
        final selected = await showDialog<ServiceCity>(
          context: context,
          builder: (_) =>
              _MarketPickerDialog(cities: cities, selectedCity: selectedCity),
        );
        if (selected != null) onChanged(selected);
      },
      child: Row(
        children: [
          const Icon(Icons.public),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Global market',
                  style: TextStyle(
                    color: AppColors.muted,
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                Text(
                  city == null
                      ? 'Choose a service city'
                      : '${city.name}, ${city.region} - ${city.currencyCode}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontWeight: FontWeight.w900),
                ),
              ],
            ),
          ),
          const Icon(Icons.keyboard_arrow_down),
        ],
      ),
    );
  }
}

class _MarketPickerDialog extends StatefulWidget {
  const _MarketPickerDialog({required this.cities, required this.selectedCity});

  final List<ServiceCity> cities;
  final ServiceCity? selectedCity;

  @override
  State<_MarketPickerDialog> createState() => _MarketPickerDialogState();
}

class _MarketPickerDialogState extends State<_MarketPickerDialog> {
  final _query = TextEditingController();

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final query = _query.text.trim().toLowerCase();
    final cities = widget.cities
        .where(
          (city) =>
              query.isEmpty ||
              city.name.toLowerCase().contains(query) ||
              city.region.toLowerCase().contains(query) ||
              city.currencyCode.toLowerCase().contains(query),
        )
        .toList();
    return AlertDialog(
      title: const Text('Choose global market'),
      content: SizedBox(
        width: 460,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _query,
              autofocus: true,
              onChanged: (_) => setState(() {}),
              decoration: const InputDecoration(
                labelText: 'Search city, country, or currency',
                prefixIcon: Icon(Icons.search),
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 420),
              child: ListView.separated(
                shrinkWrap: true,
                itemCount: cities.length,
                separatorBuilder: (_, __) => const Divider(height: 1),
                itemBuilder: (context, index) {
                  final city = cities[index];
                  final selected = city.id == widget.selectedCity?.id;
                  return ListTile(
                    leading: CircleAvatar(
                      backgroundColor: AppColors.accent.withValues(alpha: 0.1),
                      child: const Icon(
                        Icons.location_city,
                        color: AppColors.accent,
                      ),
                    ),
                    title: Text(
                      '${city.name}, ${city.region}',
                      style: const TextStyle(fontWeight: FontWeight.w900),
                    ),
                    subtitle: Text(
                      '${city.currencyCode} - ${city.locations.length} featured places - ${city.radiusKm.toStringAsFixed(0)} km service area',
                    ),
                    trailing: selected ? const Icon(Icons.check_circle) : null,
                    onTap: () => Navigator.pop(context, city),
                  );
                },
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
      ],
    );
  }
}

class _LocationEditor extends StatelessWidget {
  const _LocationEditor({
    required this.pickupController,
    required this.waypointControllers,
    required this.destinationController,
    required this.editingStop,
    required this.onFocus,
    required this.onChanged,
    required this.onAddWaypoint,
    required this.onRemoveWaypoint,
    required this.onSwap,
    this.onUseCurrentLocation,
  });

  final TextEditingController pickupController;
  final List<TextEditingController> waypointControllers;
  final TextEditingController destinationController;
  final String editingStop;
  final ValueChanged<String> onFocus;
  final void Function(String stop, String value) onChanged;
  final VoidCallback onAddWaypoint;
  final ValueChanged<int> onRemoveWaypoint;
  final VoidCallback onSwap;
  final VoidCallback? onUseCurrentLocation;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: const Color(0xFFF7F8FA),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Colors.black.withValues(alpha: 0.06)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Row(
          children: [
            Expanded(
              child: Column(
                children: [
                  _LocationField(
                    controller: pickupController,
                    label: 'Pickup',
                    icon: Icons.radio_button_checked,
                    active: editingStop == 'pickup',
                    trailing: IconButton(
                      tooltip: 'Use current location',
                      onPressed: onUseCurrentLocation,
                      icon: const Icon(Icons.near_me),
                    ),
                    onTap: () => onFocus('pickup'),
                    onChanged: (value) => onChanged('pickup', value),
                  ),
                  const SizedBox(height: 8),
                  for (var index = 0;
                      index < waypointControllers.length;
                      index += 1) ...[
                    _LocationField(
                      controller: waypointControllers[index],
                      label: 'Stop ${index + 1}',
                      icon: Icons.add_location_alt,
                      active: editingStop == 'waypoint:$index',
                      trailing: IconButton(
                        tooltip: 'Remove stop',
                        onPressed: () => onRemoveWaypoint(index),
                        icon: const Icon(Icons.close),
                      ),
                      onTap: () => onFocus('waypoint:$index'),
                      onChanged: (value) => onChanged('waypoint:$index', value),
                    ),
                    const SizedBox(height: 8),
                  ],
                  _LocationField(
                    controller: destinationController,
                    label: 'Destination',
                    icon: Icons.flag,
                    active: editingStop == 'destination',
                    onTap: () => onFocus('destination'),
                    onChanged: (value) => onChanged('destination', value),
                  ),
                  const SizedBox(height: 8),
                  Align(
                    alignment: Alignment.centerLeft,
                    child: OutlinedButton.icon(
                      onPressed: onAddWaypoint,
                      icon: const Icon(Icons.add_location_alt),
                      label: const Text('Add stop'),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            IconButton.filledTonal(
              tooltip: 'Swap pickup and destination',
              onPressed: onSwap,
              icon: const Icon(Icons.swap_vert),
            ),
          ],
        ),
      ),
    );
  }
}

class _LocationField extends StatelessWidget {
  const _LocationField({
    required this.controller,
    required this.label,
    required this.icon,
    required this.active,
    required this.onTap,
    required this.onChanged,
    this.trailing,
  });

  final TextEditingController controller;
  final String label;
  final IconData icon;
  final bool active;
  final VoidCallback onTap;
  final ValueChanged<String> onChanged;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      onTap: onTap,
      onChanged: onChanged,
      decoration: InputDecoration(
        labelText: label,
        prefixIcon: Icon(icon),
        suffixIcon: trailing,
        filled: true,
        fillColor: active ? const Color(0xFFE9FBFF) : Colors.white,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 12,
          vertical: 13,
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: BorderSide(color: Colors.black.withValues(alpha: 0.12)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: AppColors.accent, width: 2),
        ),
      ),
    );
  }
}

class _SuggestionsList extends StatelessWidget {
  const _SuggestionsList({
    required this.title,
    required this.suggestions,
    required this.onTap,
    required this.isSearching,
    this.bias,
  });

  final String title;
  final List<LocationPoint> suggestions;
  final bool isSearching;
  final LocationPoint? bias;
  final ValueChanged<LocationPoint> onTap;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: const Color(0xFFF6F7FA),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Colors.black.withValues(alpha: 0.06)),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    title,
                    style: const TextStyle(
                      color: AppColors.muted,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                ),
                if (isSearching)
                  const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
              ],
            ),
            const SizedBox(height: 6),
            if (suggestions.isEmpty && !isSearching)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 10),
                child: Text(
                  'No matching places yet. Try a more specific name.',
                  style: TextStyle(color: AppColors.muted),
                ),
              ),
            for (final location in suggestions.take(6))
              ListTile(
                dense: true,
                minLeadingWidth: 28,
                contentPadding: EdgeInsets.zero,
                leading: CircleAvatar(
                  radius: 16,
                  backgroundColor: AppColors.accent.withValues(alpha: 0.1),
                  child: const Icon(
                    Icons.place,
                    color: AppColors.accent,
                    size: 18,
                  ),
                ),
                title: Text(
                  location.address,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
                subtitle: Text(_subtitle(location)),
                onTap: () => onTap(location),
              ),
          ],
        ),
      ),
    );
  }

  String _subtitle(LocationPoint location) {
    final coordinates =
        '${location.latitude.toStringAsFixed(4)}, ${location.longitude.toStringAsFixed(4)}';
    if (bias == null) return coordinates;
    final distance = calculateHaversineDistance(
      startLatitude: bias!.latitude,
      startLongitude: bias!.longitude,
      endLatitude: location.latitude,
      endLongitude: location.longitude,
    );
    return '${distance.toStringAsFixed(1)} km away - $coordinates';
  }
}

class _TripSummary extends StatelessWidget {
  const _TripSummary({
    required this.pickup,
    required this.waypoints,
    required this.destination,
    required this.editingStop,
    required this.canEditPins,
    required this.onEditPickup,
    required this.onEditWaypoint,
    required this.onEditDestination,
  });

  final LocationPoint pickup;
  final List<LocationPoint> waypoints;
  final LocationPoint destination;
  final String editingStop;
  final bool canEditPins;
  final VoidCallback onEditPickup;
  final ValueChanged<int> onEditWaypoint;
  final VoidCallback onEditDestination;

  @override
  Widget build(BuildContext context) {
    final stops = [pickup, ...waypoints, destination];
    var distance = 0.0;
    for (var index = 1; index < stops.length; index += 1) {
      distance += calculateHaversineDistance(
        startLatitude: stops[index - 1].latitude,
        startLongitude: stops[index - 1].longitude,
        endLatitude: stops[index].latitude,
        endLongitude: stops[index].longitude,
      );
    }
    final duration = estimateTripDuration(distance).inMinutes;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AppColors.accent.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                const Icon(Icons.route, color: AppColors.accent),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    '${distance.toStringAsFixed(1)} km - about $duration min',
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                OutlinedButton.icon(
                  onPressed: canEditPins ? onEditPickup : null,
                  icon: Icon(
                    editingStop == 'pickup'
                        ? Icons.radio_button_checked
                        : Icons.trip_origin,
                  ),
                  label: const Text('Edit pickup pin'),
                ),
                for (var index = 0; index < waypoints.length; index += 1)
                  OutlinedButton.icon(
                    onPressed: canEditPins ? () => onEditWaypoint(index) : null,
                    icon: Icon(
                      editingStop == 'waypoint:$index'
                          ? Icons.radio_button_checked
                          : Icons.add_location_alt,
                    ),
                    label: Text('Edit stop ${index + 1} pin'),
                  ),
                OutlinedButton.icon(
                  onPressed: canEditPins ? onEditDestination : null,
                  icon: Icon(
                    editingStop == 'destination'
                        ? Icons.radio_button_checked
                        : Icons.flag,
                  ),
                  label: const Text('Edit destination pin'),
                ),
              ],
            ),
            if (canEditPins) ...[
              const SizedBox(height: 6),
              Text(
                editingStop == 'pickup'
                    ? 'Tap the map to move the pickup pin.'
                    : editingStop.startsWith('waypoint:')
                        ? 'Tap the map to move the selected stop pin.'
                        : 'Tap the map to move the destination pin.',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: AppColors.muted,
                      fontWeight: FontWeight.w700,
                    ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _SavedPlaces extends StatelessWidget {
  const _SavedPlaces({
    required this.places,
    required this.onPickup,
    required this.onDestination,
  });

  final List<SavedPlace> places;
  final ValueChanged<SavedPlace> onPickup;
  final ValueChanged<SavedPlace> onDestination;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final place in places.take(4))
          SegmentedButton<String>(
            segments: [
              ButtonSegment(
                value: 'destination',
                icon: const Icon(Icons.flag),
                label: Text(place.label),
              ),
              const ButtonSegment(
                value: 'pickup',
                icon: Icon(Icons.my_location),
                label: Text('Pickup'),
              ),
            ],
            selected: const {},
            emptySelectionAllowed: true,
            onSelectionChanged: (value) {
              if (value.contains('pickup')) {
                onPickup(place);
              } else {
                onDestination(place);
              }
            },
          ),
      ],
    );
  }
}

class _ResponsiveControlPair extends StatelessWidget {
  const _ResponsiveControlPair({required this.first, required this.second});

  final Widget first;
  final Widget second;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth < 360) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [first, const SizedBox(height: 8), second],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: first),
            const SizedBox(width: 8),
            Expanded(child: second),
          ],
        );
      },
    );
  }
}

class _PreQuotePanel extends StatelessWidget {
  const _PreQuotePanel({
    required this.canSeePrices,
    required this.isLoading,
    required this.hasActiveRide,
    required this.paymentMethods,
    required this.selectedPaymentMethod,
    required this.scheduledFor,
    required this.onPaymentChanged,
    required this.onScheduleChanged,
    required this.onSeePrices,
  });

  final bool canSeePrices;
  final bool isLoading;
  final bool hasActiveRide;
  final List<PaymentMethod> paymentMethods;
  final String selectedPaymentMethod;
  final DateTime? scheduledFor;
  final ValueChanged<String> onPaymentChanged;
  final ValueChanged<DateTime?> onScheduleChanged;
  final VoidCallback onSeePrices;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _ResponsiveControlPair(
            first: _PaymentControl(
              methods: paymentMethods,
              selectedPaymentMethod: selectedPaymentMethod,
              onChanged: onPaymentChanged,
            ),
            second: _ScheduleControl(
              scheduledFor: scheduledFor,
              onChanged: onScheduleChanged,
            ),
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: isLoading || hasActiveRide || !canSeePrices
                ? null
                : onSeePrices,
            child: Text(
              hasActiveRide
                  ? 'Ride in progress'
                  : canSeePrices
                      ? 'See prices'
                      : 'Enter destination',
            ),
          ),
        ],
      ),
    );
  }
}

class _RideChooser extends StatelessWidget {
  const _RideChooser({
    required this.fare,
    required this.options,
    required this.selected,
    required this.paymentMethods,
    required this.selectedPaymentMethod,
    required this.promoController,
    required this.scheduledFor,
    required this.isLoading,
    required this.hasActiveRide,
    required this.onRideChanged,
    required this.onPaymentChanged,
    required this.onScheduleChanged,
    required this.onApplyPromo,
    required this.onClearPromo,
    required this.onRequest,
  });

  final FareBreakdown fare;
  final List<RideOptionQuote> options;
  final String selected;
  final List<PaymentMethod> paymentMethods;
  final String selectedPaymentMethod;
  final TextEditingController promoController;
  final DateTime? scheduledFor;
  final bool isLoading;
  final bool hasActiveRide;
  final ValueChanged<String> onRideChanged;
  final ValueChanged<String> onPaymentChanged;
  final ValueChanged<DateTime?> onScheduleChanged;
  final Future<bool> Function() onApplyPromo;
  final Future<void> Function() onClearPromo;
  final VoidCallback onRequest;

  @override
  Widget build(BuildContext context) {
    final quotes = options.isEmpty ? _fallbackQuotes(fare) : options;
    final selectedQuote =
        quotes.where((quote) => quote.id == selected).firstOrNull ??
            quotes.first;
    return AppCard(
      padding: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Text(
              'Choose a ride',
              textAlign: TextAlign.center,
              style: Theme.of(
                context,
              ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w900),
            ),
          ),
          const Divider(height: 1),
          for (final quote in quotes)
            ListTile(
              leading: Icon(_rideIcon(quote.id), size: 32),
              title: Text(
                _rideName(quote),
                style: const TextStyle(fontWeight: FontWeight.w900),
              ),
              subtitle: Text('3 min away - ${quote.subtitle}'),
              trailing: Text(
                formatMoney(
                  quote.estimatedTotal,
                  currencySymbol: quote.currencySymbol,
                  currencyCode: quote.currencyCode,
                  currencyDecimals: quote.currencyDecimals,
                ),
                style: const TextStyle(fontWeight: FontWeight.w900),
              ),
              selected: quote.id == selected,
              onTap: () => onRideChanged(quote.id),
            ),
          const Divider(height: 1),
          Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _ResponsiveControlPair(
                  first: _PaymentControl(
                    methods: paymentMethods,
                    selectedPaymentMethod: selectedPaymentMethod,
                    onChanged: onPaymentChanged,
                  ),
                  second: _ScheduleControl(
                    scheduledFor: scheduledFor,
                    onChanged: onScheduleChanged,
                  ),
                ),
                const SizedBox(height: 12),
                _PromoCodeField(
                  controller: promoController,
                  onApplyPromo: onApplyPromo,
                  onClearPromo: onClearPromo,
                ),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: isLoading || hasActiveRide ? null : onRequest,
                  child: Text(
                    hasActiveRide
                        ? 'Ride in progress'
                        : 'Choose ${_rideName(selectedQuote)}',
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  static List<RideOptionQuote> _fallbackQuotes(FareBreakdown fare) {
    const ids = [
      ('standard', 'RideX', 'Affordable everyday rides', 1.0),
      ('comfort', 'Comfort', 'Newer cars with extra room', 1.28),
      ('plus', 'RideXL', 'Extra seats and space', 1.4),
    ];
    return ids
        .map(
          (item) => RideOptionQuote(
            id: item.$1,
            title: item.$2,
            subtitle: item.$3,
            multiplier: item.$4,
            estimatedTotal: fare.estimatedTotal * item.$4,
            currencyCode: fare.currencyCode,
            currencySymbol: fare.currencySymbol,
            currencyDecimals: fare.currencyDecimals,
          ),
        )
        .toList();
  }

  static String _rideName(RideOptionQuote quote) {
    return switch (quote.id) {
      'standard' => 'RideX',
      'plus' || 'xl' => 'RideXL',
      _ => quote.title,
    };
  }

  static IconData _rideIcon(String id) {
    return switch (id) {
      'plus' || 'xl' => Icons.airport_shuttle,
      'comfort' => Icons.event_seat,
      'green' => Icons.electric_car,
      _ => Icons.directions_car_filled,
    };
  }
}

class _PromoCodeField extends StatefulWidget {
  const _PromoCodeField({
    required this.controller,
    required this.onApplyPromo,
    required this.onClearPromo,
  });

  final TextEditingController controller;
  final Future<bool> Function() onApplyPromo;
  final Future<void> Function() onClearPromo;

  @override
  State<_PromoCodeField> createState() => _PromoCodeFieldState();
}

class _PromoCodeFieldState extends State<_PromoCodeField> {
  bool _isBusy = false;
  bool _isApplied = false;
  String _appliedCode = '';

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_handleTextChanged);
  }

  @override
  void didUpdateWidget(covariant _PromoCodeField oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller == widget.controller) return;
    oldWidget.controller.removeListener(_handleTextChanged);
    widget.controller.addListener(_handleTextChanged);
  }

  @override
  void dispose() {
    widget.controller.removeListener(_handleTextChanged);
    super.dispose();
  }

  void _handleTextChanged() {
    final code = widget.controller.text.trim();
    if (!_isApplied || code == _appliedCode) return;
    setState(() {
      _isApplied = false;
      _appliedCode = '';
    });
  }

  Future<void> _apply(BuildContext context) async {
    final code = widget.controller.text.trim();
    if (code.isEmpty || _isBusy) return;
    setState(() => _isBusy = true);
    final ok = await widget.onApplyPromo();
    if (!context.mounted) return;
    setState(() {
      _isBusy = false;
      _isApplied = ok;
      _appliedCode = ok ? code : '';
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(ok ? 'Promo applied' : 'Promo unavailable')),
    );
  }

  Future<void> _clear(BuildContext context) async {
    if (_isBusy) return;
    widget.controller.clear();
    setState(() {
      _isBusy = true;
      _isApplied = false;
      _appliedCode = '';
    });
    await widget.onClearPromo();
    if (!context.mounted) return;
    setState(() => _isBusy = false);
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(const SnackBar(content: Text('Promo removed')));
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: widget.controller,
      builder: (context, _) {
        final hasCode = widget.controller.text.trim().isNotEmpty;
        final accent = Theme.of(context).colorScheme.primary;
        return TextField(
          controller: widget.controller,
          textInputAction: TextInputAction.done,
          onSubmitted: (_) => _apply(context),
          decoration: InputDecoration(
            labelText: 'Promo code',
            prefixIcon: const Icon(Icons.local_offer),
            suffixIcon: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                IconButton(
                  tooltip: 'Use promo code',
                  onPressed: hasCode && !_isBusy ? () => _apply(context) : null,
                  icon: _isBusy
                      ? const SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : Icon(
                          _isApplied
                              ? Icons.check_circle
                              : Icons.check_circle_outline,
                          color: _isApplied ? accent : null,
                        ),
                ),
                IconButton(
                  tooltip: 'Remove promo code',
                  onPressed: hasCode && !_isBusy ? () => _clear(context) : null,
                  icon: const Icon(Icons.close),
                ),
              ],
            ),
            border: const OutlineInputBorder(),
            enabledBorder: _isApplied
                ? OutlineInputBorder(borderSide: BorderSide(color: accent))
                : const OutlineInputBorder(),
          ),
        );
      },
    );
  }
}

class _PaymentControl extends StatelessWidget {
  const _PaymentControl({
    required this.methods,
    required this.selectedPaymentMethod,
    required this.onChanged,
  });

  final List<PaymentMethod> methods;
  final String selectedPaymentMethod;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    if (methods.isEmpty) {
      return const Chip(label: Text('No payment'));
    }
    return DropdownButtonFormField<String>(
      initialValue: methods.any((item) => item.id == selectedPaymentMethod)
          ? selectedPaymentMethod
          : methods.first.id,
      decoration: const InputDecoration(
        labelText: 'Payment',
        prefixIcon: Icon(Icons.credit_card),
        border: OutlineInputBorder(),
      ),
      items: methods
          .map(
            (method) =>
                DropdownMenuItem(value: method.id, child: Text(method.label)),
          )
          .toList(),
      onChanged: (value) {
        if (value != null) onChanged(value);
      },
    );
  }
}

class _ScheduleControl extends StatelessWidget {
  const _ScheduleControl({required this.scheduledFor, required this.onChanged});

  final DateTime? scheduledFor;
  final ValueChanged<DateTime?> onChanged;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton.icon(
      onPressed: () async {
        final now = DateTime.now();
        final date = await showDatePicker(
          context: context,
          firstDate: now,
          lastDate: now.add(const Duration(days: 30)),
          initialDate: scheduledFor ?? now,
        );
        if (date == null || !context.mounted) return;
        final scheduled = await _showQuarterHourPicker(
          context: context,
          date: date,
          initialValue: scheduledFor ??
              _nextQuarterHour(now.add(const Duration(minutes: 20))),
          now: now,
        );
        if (scheduled == null) return;
        onChanged(scheduled);
      },
      icon: const Icon(Icons.schedule),
      label: Text(
        scheduledFor == null ? 'Now' : _formatTimeWindow(scheduledFor!),
      ),
    );
  }
}

DateTime _nextQuarterHour(DateTime value) {
  return _roundToNextQuarterHour(value);
}

Future<DateTime?> _showQuarterHourPicker({
  required BuildContext context,
  required DateTime date,
  required DateTime initialValue,
  required DateTime now,
}) {
  final day = DateTime(date.year, date.month, date.day);
  final today = DateTime(now.year, now.month, now.day);
  final firstSlot = day == today ? _nextQuarterHour(now) : day;
  final slots = <DateTime>[];
  for (var slot = firstSlot;
      slot.year == day.year && slot.month == day.month && slot.day == day.day;
      slot = slot.add(const Duration(minutes: 15))) {
    slots.add(slot);
  }
  final selected = _roundToNextQuarterHour(initialValue);

  return showDialog<DateTime>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text('Select pickup time'),
      content: SizedBox(
        width: 320,
        height: 360,
        child: slots.isEmpty
            ? const EmptyState('No times left today.')
            : ListView.builder(
                itemCount: slots.length,
                itemBuilder: (context, index) {
                  final slot = slots[index];
                  final isSelected = slot.hour == selected.hour &&
                      slot.minute == selected.minute;
                  return ListTile(
                    selected: isSelected,
                    leading: const Icon(Icons.schedule),
                    title: Text(_formatTimeWindow(slot)),
                    trailing: isSelected ? const Icon(Icons.check) : null,
                    onTap: () => Navigator.of(context).pop(slot),
                  );
                },
              ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
      ],
    ),
  );
}

DateTime _roundToNextQuarterHour(DateTime value) {
  final normalized = DateTime(
    value.year,
    value.month,
    value.day,
    value.hour,
    value.minute,
  );
  final totalMinutes = normalized.hour * 60 + normalized.minute;
  final roundedMinutes = ((totalMinutes + 14) ~/ 15) * 15;
  return DateTime(
    normalized.year,
    normalized.month,
    normalized.day,
  ).add(Duration(minutes: roundedMinutes));
}

String _formatClock(DateTime value) {
  return '${value.hour.toString().padLeft(2, '0')}:'
      '${value.minute.toString().padLeft(2, '0')}';
}

String _formatTimeWindow(DateTime start) {
  final end = start.add(const Duration(minutes: 15));
  return '${_formatClock(start)} - ${_formatClock(end)}';
}

Future<void> _saveInvoicePdf(BuildContext context, Ride ride) async {
  final state = context.read<AppState>();
  await state.generateInvoice(ride.id);
  if (!context.mounted) return;
  if (state.errorMessage != null) {
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(state.errorMessage!)));
    return;
  }

  final path = await saveRideInvoicePdf(ride);
  if (!context.mounted || path == null) return;
  ScaffoldMessenger.of(
    context,
  ).showSnackBar(SnackBar(content: Text('Invoice saved to $path')));
}

Map<String, dynamic>? _refundForRide(
  List<Map<String, dynamic>> refunds,
  String rideId,
) {
  for (final refund in refunds) {
    if (refund['rideId'] == rideId) return refund;
  }
  return null;
}

String _refundStatusLabel(Map<String, dynamic> refund) {
  return switch (refund['status'] as String? ?? 'requested') {
    'requested' => 'Refund requested',
    'in_review' => 'Refund in review',
    'approved' => 'Refund approved',
    'paid' => 'Refund paid',
    'rejected' => 'Refund rejected',
    _ => 'Refund requested',
  };
}

String _refundProgressMessage(Map<String, dynamic> refund) {
  final rideId = refund['rideId'] as String? ?? '';
  final reason = refund['reason'] as String? ?? 'Refund request';
  final expectedBy = refund['expectedReturnBy'] as String? ?? '';
  final status = refund['status'] as String? ?? 'requested';
  final rideText = rideId.isEmpty ? '' : 'Ride $rideId - ';
  if (status == 'approved') {
    return expectedBy.isEmpty
        ? '${rideText}Approved. Funds return within 30 days.'
        : '${rideText}Approved. Expected by ${_shortDate(expectedBy)}.';
  }
  if (status == 'paid') return '${rideText}Refund has been returned.';
  if (status == 'rejected') return '${rideText}Rejected after review.';
  return '$rideText$reason. Awaiting approval; approved refunds return within 30 days.';
}

IconData _refundStatusIcon(String status) {
  return switch (status) {
    'approved' => Icons.verified,
    'paid' => Icons.check_circle,
    'rejected' => Icons.block,
    'in_review' => Icons.manage_search,
    _ => Icons.hourglass_top,
  };
}

String _shortDate(String value) {
  final parsed = DateTime.tryParse(value);
  if (parsed == null) return value;
  return '${parsed.year}-${parsed.month.toString().padLeft(2, '0')}-'
      '${parsed.day.toString().padLeft(2, '0')}';
}

class _ActiveNotice extends StatelessWidget {
  const _ActiveNotice({required this.ride, required this.onOpen});

  final Ride ride;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AppColors.ink,
        borderRadius: BorderRadius.circular(18),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                const Icon(Icons.local_taxi, color: Colors.white),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    _activeTitle(ride),
                    style: const TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                ),
                TextButton(
                  onPressed: onOpen,
                  child: const Text(
                    'View',
                    style: TextStyle(color: Colors.white),
                  ),
                ),
              ],
            ),
            if (ride.canCancel)
              OutlinedButton.icon(
                onPressed: () => context.read<AppState>().cancelRide(ride.id),
                icon: const Icon(Icons.cancel),
                label: const Text('Cancel ride'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.danger,
                  side: const BorderSide(color: AppColors.danger),
                ),
              ),
          ],
        ),
      ),
    );
  }

  String _activeTitle(Ride ride) {
    if (ride.driver != null) return '${ride.driver!.name} is assigned';
    return 'Searching for driver';
  }
}

class _CancelledRidePanel extends StatelessWidget {
  const _CancelledRidePanel({
    required this.ride,
    required this.onDismiss,
    required this.onRequestRide,
  });

  final Ride ride;
  final VoidCallback onDismiss;
  final VoidCallback onRequestRide;

  @override
  Widget build(BuildContext context) {
    final reason = ride.timeline
        .where((entry) => entry.status == 'cancelled')
        .map((entry) => entry.label)
        .firstOrNull;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                'Ride canceled',
                style: Theme.of(context).textTheme.titleLarge,
              ),
            ),
            const RideStatusBadge('cancelled'),
          ],
        ),
        const SizedBox(height: 12),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Row(
                children: [
                  Icon(Icons.cancel, color: AppColors.danger),
                  SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      'This trip was canceled.',
                      style: TextStyle(fontWeight: FontWeight.w900),
                    ),
                  ),
                ],
              ),
              if (reason != null && reason.trim().isNotEmpty) ...[
                const SizedBox(height: 10),
                Text(
                  reason,
                  style: const TextStyle(color: AppColors.muted),
                ),
              ],
              const SizedBox(height: 14),
              _CanceledRideRow(label: 'Pickup', value: ride.pickupAddress),
              const SizedBox(height: 8),
              for (var index = 0; index < ride.waypoints.length; index += 1)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: _CanceledRideRow(
                    label: 'Stop ${index + 1}',
                    value: ride.waypoints[index].address,
                  ),
                ),
              _CanceledRideRow(
                label: 'Destination',
                value: ride.destinationAddress,
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        FilledButton.icon(
          onPressed: onRequestRide,
          icon: const Icon(Icons.map),
          label: const Text('Request a ride'),
        ),
        const SizedBox(height: 10),
        OutlinedButton.icon(
          onPressed: onDismiss,
          icon: const Icon(Icons.check),
          label: const Text('Done'),
        ),
      ],
    );
  }
}

class _CanceledRideRow extends StatelessWidget {
  const _CanceledRideRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 92,
          child: Text(label, style: const TextStyle(color: AppColors.muted)),
        ),
        Expanded(
          child:
              Text(value, style: const TextStyle(fontWeight: FontWeight.w800)),
        ),
      ],
    );
  }
}

class RiderActiveRidePanel extends StatelessWidget {
  const RiderActiveRidePanel({required this.ride, super.key});

  final Ride ride;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                'Active ride',
                style: Theme.of(context).textTheme.titleLarge,
              ),
            ),
            RideStatusBadge(ride.status),
          ],
        ),
        const SizedBox(height: 12),
        DriverInfoCard(
          ride: ride,
          onMessage: ride.hasConfirmedDriver
              ? () => showDialog<void>(
                    context: context,
                    builder: (_) => RideMessageDialog(ride: ride),
                  )
              : null,
          onSafety: () => showDialog<void>(
            context: context,
            builder: (_) => RideSafetyDialog(ride: ride),
          ),
        ),
        const SizedBox(height: 12),
        _RideProgressAction(ride: ride),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          onPressed: () => showDialog<void>(
            context: context,
            builder: (_) => RideStopsDialog(ride: ride),
          ),
          icon: const Icon(Icons.add_location_alt),
          label: Text(ride.waypoints.isEmpty ? 'Add stop' : 'Edit stops'),
        ),
        const SizedBox(height: 12),
        TripCard(ride: ride),
        const SizedBox(height: 12),
        RideTimeline(status: ride.status, entries: ride.timeline),
        if (ride.canCancel)
          OutlinedButton.icon(
            onPressed: () => context.read<AppState>().cancelRide(ride.id),
            icon: const Icon(Icons.cancel),
            label: const Text('Cancel ride'),
          ),
      ],
    );
  }
}

class _RideProgressAction extends StatelessWidget {
  const _RideProgressAction({required this.ride});

  final Ride ride;

  @override
  Widget build(BuildContext context) {
    final data = switch (ride.status) {
      'scheduled' => (
          Icons.event_available,
          'Ride scheduled',
          'Driver matching starts closer to pickup.',
        ),
      'requested' => (Icons.schedule, 'Request received', 'Finding drivers.'),
      'searching' => (
          Icons.radar,
          'Waiting for driver response',
          'Nearby approved drivers are being contacted.',
        ),
      'accepted' => (
          Icons.local_taxi,
          'Driver accepted',
          'Your driver is preparing to head to pickup.',
        ),
      'driver_arriving' => (
          Icons.near_me,
          'Driver is on the way',
          'Track the car on the map.',
        ),
      'arrived' => (
          Icons.task_alt,
          'Driver has arrived',
          'The driver should message you and wait at pickup.',
        ),
      'in_progress' => (
          Icons.route,
          'Trip in progress',
          'Driving to destination.',
        ),
      _ => (Icons.receipt_long, 'Trip completed', 'Receipt is ready.'),
    };
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AppColors.accent.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.accent.withValues(alpha: 0.18)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                CircleAvatar(
                  backgroundColor: AppColors.accent.withValues(alpha: 0.12),
                  child: Icon(data.$1, color: AppColors.accent),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        data.$2,
                        style: const TextStyle(fontWeight: FontWeight.w900),
                      ),
                      Text(
                        data.$3,
                        style: const TextStyle(color: AppColors.muted),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            if (ride.status == 'arrived') ...[
              const SizedBox(height: 12),
              FilledButton.icon(
                onPressed: () =>
                    context.read<AppState>().confirmBoarding(ride.id),
                icon: const Icon(Icons.directions_car_filled),
                label: const Text('Confirm pickup'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class RideStopsDialog extends StatefulWidget {
  const RideStopsDialog({required this.ride, super.key});

  final Ride ride;

  @override
  State<RideStopsDialog> createState() => _RideStopsDialogState();
}

class _RideStopsDialogState extends State<RideStopsDialog> {
  final _controllers = <TextEditingController>[];
  final _points = <LocationPoint?>[];
  int _activeIndex = 0;

  @override
  void initState() {
    super.initState();
    for (final point in widget.ride.waypoints) {
      _controllers.add(TextEditingController(text: point.address));
      _points.add(point);
    }
    if (_controllers.isEmpty) _addStop();
  }

  @override
  void dispose() {
    for (final controller in _controllers) {
      controller.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final suggestions = _suggestions(state);
    return AlertDialog(
      title: const Text('Edit stops'),
      content: SizedBox(
        width: 520,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 280),
              child: ListView.separated(
                shrinkWrap: true,
                itemCount: _controllers.length,
                separatorBuilder: (_, __) => const SizedBox(height: 8),
                itemBuilder: (context, index) {
                  return TextField(
                    controller: _controllers[index],
                    onTap: () => setState(() => _activeIndex = index),
                    onChanged: (value) {
                      setState(() {
                        _activeIndex = index;
                        _points[index] = null;
                      });
                    },
                    decoration: InputDecoration(
                      labelText: 'Stop ${index + 1}',
                      prefixIcon: const Icon(Icons.add_location_alt),
                      suffixIcon: IconButton(
                        tooltip: 'Remove stop',
                        onPressed: _controllers.length == 1
                            ? null
                            : () => _removeStop(index),
                        icon: const Icon(Icons.close),
                      ),
                      border: const OutlineInputBorder(),
                    ),
                  );
                },
              ),
            ),
            const SizedBox(height: 10),
            OutlinedButton.icon(
              onPressed: _addStop,
              icon: const Icon(Icons.add),
              label: const Text('Add another stop'),
            ),
            const SizedBox(height: 12),
            DecoratedBox(
              decoration: BoxDecoration(
                color: const Color(0xFFF6F7FA),
                borderRadius: BorderRadius.circular(14),
              ),
              child: Padding(
                padding: const EdgeInsets.all(10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            'Matches for stop ${_activeIndex + 1}',
                            style: const TextStyle(
                              color: AppColors.muted,
                              fontWeight: FontWeight.w900,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    ConstrainedBox(
                      constraints: const BoxConstraints(maxHeight: 190),
                      child: ListView(
                        shrinkWrap: true,
                        children: [
                          for (final location in suggestions.take(6))
                            ListTile(
                              dense: true,
                              contentPadding: EdgeInsets.zero,
                              leading: const Icon(
                                Icons.place,
                                color: AppColors.accent,
                              ),
                              title: Text(
                                location.address,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  fontWeight: FontWeight.w800,
                                ),
                              ),
                              subtitle: Text(
                                '${location.latitude.toStringAsFixed(4)}, ${location.longitude.toStringAsFixed(4)}',
                              ),
                              onTap: () => _setStop(location),
                            ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton.icon(
          onPressed: state.isLoading ? null : () => _save(context),
          icon: const Icon(Icons.check),
          label: const Text('Save stops'),
        ),
      ],
    );
  }

  void _addStop() {
    setState(() {
      _controllers.add(TextEditingController());
      _points.add(null);
      _activeIndex = _controllers.length - 1;
    });
  }

  void _removeStop(int index) {
    setState(() {
      _controllers.removeAt(index).dispose();
      _points.removeAt(index);
      _activeIndex = _activeIndex.clamp(0, _controllers.length - 1).toInt();
    });
  }

  void _setStop(LocationPoint location) {
    setState(() {
      _controllers[_activeIndex].text = location.address;
      _points[_activeIndex] = location;
    });
  }

  Future<void> _save(BuildContext context) async {
    final state = context.read<AppState>();
    final waypoints = <LocationPoint>[];
    for (var index = 0; index < _controllers.length; index += 1) {
      final point =
          _points[index] ?? _exactMatch(state, _controllers[index].text);
      if (point != null) waypoints.add(point);
    }
    await state.updateRideWaypoints(widget.ride.id, waypoints);
    if (!context.mounted) return;
    Navigator.pop(context);
  }

  List<LocationPoint> _suggestions(AppState state) {
    final query = _controllers.isEmpty
        ? ''
        : _controllers[_activeIndex].text.trim().toLowerCase();
    final locations = _allLocations(state);
    final bias = _activeSearchBias();
    if (query.isEmpty) {
      return _rankedLocations(locations, state, query, bias).take(5).toList();
    }
    final merged = <String, LocationPoint>{};
    for (final location in _keywordFallbacks(state, query)) {
      merged[_key(location)] = location;
    }
    for (final location in _offlineGazetteerSuggestions(state, query)) {
      merged[_key(location)] = location;
    }
    final matches = _allServiceLocations(
      state,
    ).where((location) => _matchesLocationQuery(location, query)).toList()
      ..sort((a, b) {
        final selectedId = state.selectedCity?.id ?? '';
        final aLocal = a.cityId == selectedId ? 0 : 1;
        final bLocal = b.cityId == selectedId ? 0 : 1;
        final localCompare = aLocal.compareTo(bLocal);
        if (localCompare != 0) return localCompare;
        return _locationScore(b, query).compareTo(_locationScore(a, query));
      });
    for (final city in state.serviceCities.where(
      (city) =>
          city.name.toLowerCase().contains(query) ||
          city.region.toLowerCase().contains(query) ||
          city.currencyCode.toLowerCase().contains(query),
    )) {
      final location = LocationPoint(
        id: city.centerLocation.id,
        cityId: city.id,
        address: '${city.name}, ${city.region} service area',
        latitude: city.centerLatitude,
        longitude: city.centerLongitude,
      );
      merged[_key(location)] = location;
    }
    for (final location in matches) {
      merged[_key(location)] = location;
    }
    return _rankedLocations(
      merged.values.toList(),
      state,
      query,
      bias,
    ).take(8).toList();
  }

  LocationPoint _activeSearchBias() {
    if (_activeIndex > 0 && _points[_activeIndex - 1] != null) {
      return _points[_activeIndex - 1]!;
    }
    return LocationPoint(
      address: widget.ride.pickupAddress,
      latitude: widget.ride.pickupLatitude,
      longitude: widget.ride.pickupLongitude,
    );
  }

  List<LocationPoint> _rankedLocations(
    List<LocationPoint> locations,
    AppState state,
    String query,
    LocationPoint? bias,
  ) {
    final selectedId = state.selectedCity?.id ?? '';
    return List<LocationPoint>.from(locations)
      ..sort((a, b) {
        final aScore = _locationScore(a, query);
        final bScore = _locationScore(b, query);
        final scoreDelta = bScore - aScore;
        if (scoreDelta.abs() >= 8) return scoreDelta;

        final aDistance = _distanceFromBiasKm(bias, a);
        final bDistance = _distanceFromBiasKm(bias, b);
        final distanceCompare = aDistance.compareTo(bDistance);
        if (distanceCompare != 0) return distanceCompare;

        final aLocal = a.cityId == selectedId ? 0 : 1;
        final bLocal = b.cityId == selectedId ? 0 : 1;
        final localCompare = aLocal.compareTo(bLocal);
        if (localCompare != 0) return localCompare;

        return scoreDelta;
      });
  }

  double _distanceFromBiasKm(LocationPoint? bias, LocationPoint location) {
    if (bias == null) return double.infinity;
    return calculateHaversineDistance(
      startLatitude: bias.latitude,
      startLongitude: bias.longitude,
      endLatitude: location.latitude,
      endLongitude: location.longitude,
    );
  }

  LocationPoint? _exactMatch(AppState state, String value) {
    final query = value.trim().toLowerCase();
    if (query.isEmpty) return null;
    final locations = [
      ..._allServiceLocations(state),
    ];
    for (final location in locations) {
      if (location.address.toLowerCase() == query) return location;
    }
    return null;
  }

  String _key(LocationPoint location) {
    return '${_normalizeLocationAddress(location.address)}_'
        '${location.latitude.toStringAsFixed(4)}_'
        '${location.longitude.toStringAsFixed(4)}';
  }

  List<LocationPoint> _allLocations(AppState state) {
    final city = state.selectedCity;
    final locations =
        city?.locations.isNotEmpty == true ? city!.locations : state.locations;
    final deduped = <LocationPoint>[];
    for (final location in [
      LocationPoint(
        address: widget.ride.pickupAddress,
        latitude: widget.ride.pickupLatitude,
        longitude: widget.ride.pickupLongitude,
      ),
      LocationPoint(
        address: widget.ride.destinationAddress,
        latitude: widget.ride.destinationLatitude,
        longitude: widget.ride.destinationLongitude,
      ),
      ...locations,
      ..._offlineGazetteerLocations(state),
    ]) {
      _addUniqueLocation(deduped, location);
    }
    return deduped;
  }

  List<LocationPoint> _allServiceLocations(AppState state) {
    return [
      ...state.serviceCities.expand((city) => city.locations),
      ..._offlineGazetteerLocations(state),
    ];
  }

  bool _addUniqueLocation(List<LocationPoint> locations, LocationPoint next) {
    if (locations.any((location) => _sameSearchLocation(location, next))) {
      return false;
    }
    locations.add(next);
    return true;
  }

  bool _sameSearchLocation(LocationPoint a, LocationPoint b) {
    if (_key(a) == _key(b)) return true;
    final distance = calculateHaversineDistance(
      startLatitude: a.latitude,
      startLongitude: a.longitude,
      endLatitude: b.latitude,
      endLongitude: b.longitude,
    );
    if (distance > 0.08) return false;
    final aText = _normalizeLocationAddress(a.address);
    final bText = _normalizeLocationAddress(b.address);
    if (aText == bText || aText.contains(bText) || bText.contains(aText)) {
      return true;
    }
    final aTokens = aText.split(' ').where((token) => token.length > 2).toSet();
    final bTokens = bText.split(' ').where((token) => token.length > 2).toSet();
    if (aTokens.isEmpty || bTokens.isEmpty) return false;
    return aTokens.intersection(bTokens).length >= 2;
  }

  bool _matchesLocationQuery(LocationPoint location, String query) {
    final normalizedQuery = _normalizeLocationAddress(query);
    if (normalizedQuery.isEmpty) {
      return _locationAliases(
        location,
      ).any((alias) => query.toLowerCase().contains(alias.toLowerCase()));
    }
    final searchTexts = _locationSearchTexts(location);
    if (searchTexts.any((text) => text.contains(normalizedQuery))) {
      return true;
    }
    final queryTokens = normalizedQuery
        .split(' ')
        .where((token) => token.length > 1)
        .toList(growable: false);
    if (queryTokens.isEmpty) return false;
    return searchTexts.any(
      (text) => queryTokens.every((token) => text.contains(token)),
    );
  }

  int _locationScore(LocationPoint location, String query) {
    final normalizedQuery = _normalizeLocationAddress(query);
    var score = 0;
    for (final text in _locationSearchTexts(location)) {
      if (text.startsWith(normalizedQuery)) score += 8;
      if (text.contains(normalizedQuery)) score += 4;
      for (final token in normalizedQuery.split(' ')) {
        if (token.length > 1 && text.contains(token)) score += 1;
      }
    }
    return score;
  }

  List<String> _locationSearchTexts(LocationPoint location) {
    return [
      location.address,
      location.id.replaceAll('_', ' '),
      ..._locationAliases(location),
    ]
        .map(_normalizeLocationAddress)
        .where((text) => text.isNotEmpty)
        .toSet()
        .toList(growable: false);
  }

  List<String> _locationAliases(LocationPoint location) {
    final id = location.id.toLowerCase();
    final address = _normalizeLocationAddress(location.address);
    if (id == 'nyu' || address.contains('new york university')) {
      return const ['nyu', 'new york university'];
    }
    return const [];
  }

  String _normalizeLocationAddress(String value) {
    return value
        .toLowerCase()
        .replaceAll('&', ' and ')
        .replaceAll(RegExp(r'[^a-z0-9]+'), ' ')
        .replaceAll(
          RegExp(
            r'\b(street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|suite|ste|floor|fl)\b',
          ),
          ' ',
        )
        .replaceAll(RegExp(r'\s+'), ' ')
        .trim();
  }

  List<LocationPoint> _keywordFallbacks(AppState state, String query) {
    final cityId = state.selectedCity?.id ?? '';
    final normalizedQuery = _normalizeLocationAddress(query);
    if (cityId == 'new_york' &&
        (normalizedQuery.contains('nyu') ||
            normalizedQuery.contains('new york university'))) {
      return const [
        LocationPoint(
          id: 'nyu',
          cityId: 'new_york',
          address: 'New York University, Greenwich Village, New York, NY',
          latitude: 40.7295,
          longitude: -73.9965,
        ),
      ];
    }
    if (cityId == 'sf_bay' && query.contains('zoom')) {
      return const [
        LocationPoint(
          cityId: 'sf_bay',
          address: 'Zoom Room Dog Training, 1412 El Camino Real, Belmont, CA',
          latitude: 37.5172,
          longitude: -122.2758,
        ),
        LocationPoint(
          cityId: 'sf_bay',
          address:
              'Zoom Video Communications, 55 Almaden Boulevard, San Jose, CA',
          latitude: 37.3322,
          longitude: -121.8911,
        ),
      ];
    }
    if (cityId == 'sf_bay' && query.contains('meta')) {
      return const [
        LocationPoint(
          cityId: 'sf_bay',
          address: 'Meta MPK 23, 300 Constitution Drive, Menlo Park, CA',
          latitude: 37.4803,
          longitude: -122.1669,
        ),
        LocationPoint(
          cityId: 'sf_bay',
          address: 'Meta Park, Menlo Park, California, United States',
          latitude: 37.4807,
          longitude: -122.1623,
        ),
        LocationPoint(
          cityId: 'sf_bay',
          address: 'Meta West Campus, Menlo Park, California, United States',
          latitude: 37.4813,
          longitude: -122.1592,
        ),
        LocationPoint(
          cityId: 'sf_bay',
          address: 'Meta MPK 20, 1 Meta Way, Menlo Park, California',
          latitude: 37.4810,
          longitude: -122.1542,
        ),
        LocationPoint(
          cityId: 'sf_bay',
          address: 'Meta MPK 22, 1 Meta Way, Menlo Park, California',
          latitude: 37.4819,
          longitude: -122.1636,
        ),
      ];
    }
    return const [];
  }

  List<LocationPoint> _offlineGazetteerSuggestions(
    AppState state,
    String query,
  ) {
    final matches = _offlineGazetteerLocations(
      state,
    ).where((location) => _matchesLocationQuery(location, query)).toList();
    final selectedId = state.selectedCity?.id ?? '';
    matches.sort((a, b) {
      final aLocal = a.cityId == selectedId ? 0 : 1;
      final bLocal = b.cityId == selectedId ? 0 : 1;
      final localCompare = aLocal.compareTo(bLocal);
      if (localCompare != 0) return localCompare;
      return _locationScore(b, query).compareTo(_locationScore(a, query));
    });
    return matches;
  }

  List<LocationPoint> _offlineGazetteerLocations(AppState state) {
    final enabledCityIds = state.serviceCities.map((city) => city.id).toSet();
    return _offlineGazetteer
        .where((location) => enabledCityIds.contains(location.cityId))
        .toList(growable: false);
  }
}

class RideMessageDialog extends StatefulWidget {
  const RideMessageDialog({required this.ride, super.key});

  final Ride ride;

  @override
  State<RideMessageDialog> createState() => _RideMessageDialogState();
}

class _RideMessageDialogState extends State<RideMessageDialog> {
  final _message = TextEditingController();

  @override
  void dispose() {
    _message.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final ride = state.activeRide?.id == widget.ride.id
        ? state.activeRide!
        : widget.ride;
    final messages = ride.messages;
    return AlertDialog(
      title: Text('Message ${ride.driver?.name ?? 'driver'}'),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 260),
              child: messages.isEmpty
                  ? const EmptyState(
                      'No messages yet. Your conversation appears here.',
                    )
                  : ListView.separated(
                      shrinkWrap: true,
                      itemCount: messages.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 8),
                      itemBuilder: (context, index) {
                        final item = messages[index];
                        final mine = item.senderRole == 'rider';
                        return Align(
                          alignment: mine
                              ? Alignment.centerRight
                              : Alignment.centerLeft,
                          child: Container(
                            constraints: const BoxConstraints(maxWidth: 310),
                            padding: const EdgeInsets.symmetric(
                              horizontal: 12,
                              vertical: 9,
                            ),
                            decoration: BoxDecoration(
                              color: mine
                                  ? AppColors.accent
                                  : const Color(0xFFF1F4F8),
                              borderRadius: BorderRadius.circular(14),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  item.senderName,
                                  style: TextStyle(
                                    color:
                                        mine ? Colors.white70 : AppColors.muted,
                                    fontSize: 11,
                                    fontWeight: FontWeight.w800,
                                  ),
                                ),
                                const SizedBox(height: 2),
                                Text(
                                  item.body,
                                  style: TextStyle(
                                    color: mine ? Colors.white : AppColors.ink,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        );
                      },
                    ),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final reply in _quickReplies(ride.status))
                  ActionChip(
                    label: Text(reply),
                    onPressed: () => _send(context, reply),
                  ),
              ],
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _message,
              minLines: 1,
              maxLines: 3,
              decoration: const InputDecoration(
                labelText: 'Type a message',
                border: OutlineInputBorder(),
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Close'),
        ),
        FilledButton.icon(
          onPressed: state.isLoading
              ? null
              : () => _send(context, _message.text.trim()),
          icon: const Icon(Icons.send),
          label: const Text('Send'),
        ),
      ],
    );
  }

  List<String> _quickReplies(String status) {
    return switch (status) {
      'arrived' => [
          'I am coming out now.',
          'Please wait 2 minutes.',
          'Where exactly are you parked?',
        ],
      'driver_arriving' => [
          'I am at the pickup spot.',
          'Please call when you arrive.',
          'I have luggage.',
        ],
      'in_progress' => [
          'Can you take the safest route?',
          'Please adjust the temperature.',
          'I need to update the destination.',
        ],
      _ => ['Thanks', 'Please call me', 'I am nearby'],
    };
  }

  Future<void> _send(BuildContext context, String body) async {
    final clean = body.trim();
    if (clean.isEmpty) return;
    await context.read<AppState>().sendRideMessage(widget.ride.id, clean);
    if (!context.mounted) return;
    _message.clear();
  }
}

class RideSafetyDialog extends StatelessWidget {
  const RideSafetyDialog({required this.ride, super.key});

  final Ride ride;

  @override
  Widget build(BuildContext context) {
    final plate = ride.driverProfile?.licensePlate ?? 'vehicle plate';
    return AlertDialog(
      title: const Text('Trip safety'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _SafetyRow(
            icon: Icons.badge,
            title: 'Verify vehicle',
            message: 'Confirm $plate before getting in.',
          ),
          const _SafetyRow(
            icon: Icons.ios_share,
            title: 'Share trip',
            message: 'Share live status with a trusted contact.',
          ),
          const _SafetyRow(
            icon: Icons.emergency,
            title: 'Emergency help',
            message: 'Contact emergency services if you feel unsafe.',
          ),
          const _SafetyRow(
            icon: Icons.pin,
            title: 'Ride PIN',
            message: 'Use the trip PIN when the market requires it.',
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Close'),
        ),
      ],
    );
  }
}

class _SafetyRow extends StatelessWidget {
  const _SafetyRow({
    required this.icon,
    required this.title,
    required this.message,
  });

  final IconData icon;
  final String title;
  final String message;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Icon(icon, color: AppColors.accent),
      title: Text(title, style: const TextStyle(fontWeight: FontWeight.w900)),
      subtitle: Text(message),
    );
  }
}

class _RideRecordActions extends StatelessWidget {
  const _RideRecordActions({required this.ride});

  final Ride ride;

  @override
  Widget build(BuildContext context) {
    final refunds = context.watch<AppState>().refunds;
    final refund = _refundForRide(refunds, ride.id);
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          FilledButton.tonalIcon(
            onPressed: () => _saveInvoicePdf(context, ride),
            icon: const Icon(Icons.picture_as_pdf),
            label: const Text('Save invoice PDF'),
          ),
          if (refund == null)
            OutlinedButton.icon(
              onPressed: () => showDialog<void>(
                context: context,
                builder: (_) => RequestRefundDialog(ride: ride),
              ),
              icon: const Icon(Icons.replay),
              label: const Text('Request refund'),
            )
          else
            OutlinedButton.icon(
              onPressed: null,
              icon: const Icon(Icons.hourglass_top),
              label: Text(_refundStatusLabel(refund)),
            ),
        ],
      ),
    );
  }
}

class _SupportTicketRow extends StatelessWidget {
  const _SupportTicketRow({required this.ticket});

  final SupportTicket ticket;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Icon(_supportStatusIcon(ticket.status), color: AppColors.accent),
      title: Text(
        '${ticket.category} - ${_supportStatusLabel(ticket.status)}',
        style: const TextStyle(fontWeight: FontWeight.w900),
      ),
      subtitle: Text(
        [
          'Ticket ${ticket.id}',
          ticket.message,
          ticket.replies.isEmpty
              ? 'Waiting for support response.'
              : '${ticket.replies.length} replies. Latest: ${ticket.replies.last.message}',
        ].join('\n'),
      ),
      trailing: IconButton(
        tooltip: 'Reply to ticket',
        onPressed: () => showDialog<void>(
          context: context,
          builder: (_) => SupportReplyDialog(ticket: ticket),
        ),
        icon: const Icon(Icons.reply),
      ),
    );
  }
}

String _supportStatusLabel(String status) {
  return switch (status) {
    'open' => 'Open',
    'in_review' => 'In review',
    'resolved' => 'Resolved',
    'closed' => 'Closed',
    _ => status.replaceAll('_', ' '),
  };
}

IconData _supportStatusIcon(String status) {
  return switch (status) {
    'resolved' => Icons.check_circle,
    'closed' => Icons.lock,
    'in_review' => Icons.manage_search,
    _ => Icons.confirmation_number,
  };
}

class _RightRail extends StatelessWidget {
  const _RightRail({required this.activeRide});

  final Ride activeRide;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Trip status',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 8),
              RideTimeline(
                status: activeRide.status,
                entries: activeRide.timeline,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _AccountCard extends StatefulWidget {
  const _AccountCard({required this.title, required this.children});

  final String title;
  final List<Widget> children;

  @override
  State<_AccountCard> createState() => _AccountCardState();
}

class _AccountCardState extends State<_AccountCard> {
  late bool _expanded;

  @override
  void initState() {
    super.initState();
    _expanded = false;
  }

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            borderRadius: BorderRadius.circular(8),
            onTap: () => setState(() => _expanded = !_expanded),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      widget.title,
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                  ),
                  AnimatedRotation(
                    turns: _expanded ? 0.5 : 0,
                    duration: const Duration(milliseconds: 180),
                    child: const Icon(Icons.expand_more),
                  ),
                ],
              ),
            ),
          ),
          AnimatedCrossFade(
            firstChild: const SizedBox.shrink(),
            secondChild: Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: widget.children,
              ),
            ),
            crossFadeState: _expanded
                ? CrossFadeState.showSecond
                : CrossFadeState.showFirst,
            duration: const Duration(milliseconds: 180),
          ),
        ],
      ),
    );
  }
}

class _StatChip extends StatelessWidget {
  const _StatChip({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Chip(
      avatar: Icon(icon, size: 16, color: AppColors.accent),
      label: Text(label),
      backgroundColor: AppColors.accent.withValues(alpha: 0.08),
      side: BorderSide.none,
    );
  }
}

class _WalletRow extends StatelessWidget {
  const _WalletRow({
    required this.icon,
    required this.label,
    required this.value,
  });

  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        children: [
          Icon(icon, size: 18, color: AppColors.muted),
          const SizedBox(width: 8),
          Expanded(child: Text(label)),
          Text(value, style: const TextStyle(fontWeight: FontWeight.w900)),
        ],
      ),
    );
  }
}

class _CouponRow extends StatelessWidget {
  const _CouponRow({required this.coupon});

  final Map<String, dynamic> coupon;

  @override
  Widget build(BuildContext context) {
    final code = coupon['code'] as String? ?? 'COUPON';
    final title = coupon['title'] as String? ?? 'Ride coupon';
    final status = coupon['status'] as String? ?? 'available';
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: const Icon(Icons.local_offer, color: AppColors.accent),
      title: Text(code, style: const TextStyle(fontWeight: FontWeight.w900)),
      subtitle: Text('$title - ${_couponDiscount(coupon)}'),
      trailing: Wrap(
        spacing: 4,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          Chip(label: Text(status), side: BorderSide.none),
          IconButton(
            tooltip: 'Copy coupon code',
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: code));
              if (!context.mounted) return;
              ScaffoldMessenger.of(
                context,
              ).showSnackBar(SnackBar(content: Text('$code copied')));
            },
            icon: const Icon(Icons.copy),
          ),
        ],
      ),
    );
  }

  String _couponDiscount(Map<String, dynamic> coupon) {
    if (coupon['discountType'] == 'percent') {
      return '${(coupon['percentOff'] as num?)?.toInt() ?? 0}% off';
    }
    if (coupon['discountType'] == 'amount') {
      return '${formatMoney((coupon['amountOff'] as num?)?.toDouble() ?? 0)} off';
    }
    return 'discount';
  }
}

class _PaymentMethodRow extends StatelessWidget {
  const _PaymentMethodRow({required this.method, required this.canDelete});

  final PaymentMethod method;
  final bool canDelete;

  @override
  Widget build(BuildContext context) {
    final state = context.read<AppState>();
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Icon(
        method.type == 'wallet'
            ? Icons.account_balance_wallet
            : Icons.credit_card,
        color: AppColors.accent,
      ),
      title: Text(
        method.label,
        style: const TextStyle(fontWeight: FontWeight.w900),
      ),
      subtitle: Text('${method.brand} ending ${method.last4}'),
      trailing: Wrap(
        spacing: 4,
        children: [
          if (method.isDefault)
            const Chip(label: Text('Default'), side: BorderSide.none)
          else
            IconButton(
              tooltip: 'Set default payment',
              onPressed: () => state.setDefaultPaymentMethod(method.id),
              icon: const Icon(Icons.star_outline),
            ),
          IconButton(
            tooltip: canDelete
                ? 'Delete payment method'
                : 'At least one payment method is required',
            onPressed:
                canDelete ? () => state.deletePaymentMethod(method.id) : null,
            icon: const Icon(Icons.delete_outline),
          ),
        ],
      ),
    );
  }
}

class _MoneyMapRow extends StatelessWidget {
  const _MoneyMapRow({
    required this.icon,
    required this.title,
    required this.amount,
    required this.status,
    this.currencySymbol = r'$',
    this.currencyCode = 'USD',
    this.currencyDecimals = 2,
  });

  final IconData icon;
  final String title;
  final double amount;
  final String status;
  final String currencySymbol;
  final String currencyCode;
  final int currencyDecimals;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Icon(icon, color: AppColors.accent),
      title: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text(status),
      trailing: Text(
        formatMoney(
          amount,
          currencySymbol: currencySymbol,
          currencyCode: currencyCode,
          currencyDecimals: currencyDecimals,
        ),
        style: const TextStyle(fontWeight: FontWeight.w900),
      ),
    );
  }
}

class _RefundProgressRow extends StatelessWidget {
  const _RefundProgressRow({required this.refund});

  final Map<String, dynamic> refund;

  @override
  Widget build(BuildContext context) {
    final amount = (refund['amount'] as num?)?.toDouble() ?? 0;
    final status = refund['status'] as String? ?? 'requested';
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Icon(_refundStatusIcon(status), color: AppColors.accent),
      title: Text(
        _refundStatusLabel(refund),
        style: const TextStyle(fontWeight: FontWeight.w900),
      ),
      subtitle: Text(_refundProgressMessage(refund)),
      trailing: Text(
        formatMoney(
          amount,
          currencySymbol: refund['currencySymbol'] as String? ?? r'$',
          currencyCode: refund['currencyCode'] as String? ?? 'USD',
          currencyDecimals: (refund['currencyDecimals'] as num?)?.toInt() ?? 2,
        ),
        style: const TextStyle(fontWeight: FontWeight.w900),
      ),
    );
  }
}

class _AccountNotificationRow extends StatelessWidget {
  const _AccountNotificationRow({required this.notification});

  final NotificationItem notification;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Icon(
        notification.read
            ? Icons.notifications_none
            : Icons.notifications_active,
        color: notification.read ? AppColors.muted : AppColors.accent,
      ),
      title: Text(notification.title),
      subtitle: Text(notification.message),
      trailing: notification.read
          ? null
          : IconButton(
              tooltip: 'Mark read',
              onPressed: () => context.read<AppState>().markNotificationRead(
                    notification.id,
                  ),
              icon: const Icon(Icons.done),
            ),
      onTap: notification.read
          ? null
          : () =>
              context.read<AppState>().markNotificationRead(notification.id),
    );
  }
}

class _PlainMapRow extends StatelessWidget {
  const _PlainMapRow({
    required this.icon,
    required this.title,
    required this.subtitle,
  });

  final IconData icon;
  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Icon(icon, color: AppColors.accent),
      title: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text(subtitle),
    );
  }
}

class _SavePlaceDialog extends StatefulWidget {
  const _SavePlaceDialog({required this.defaultLabel});

  final String defaultLabel;

  @override
  State<_SavePlaceDialog> createState() => _SavePlaceDialogState();
}

class _SavePlaceDialogState extends State<_SavePlaceDialog> {
  late final TextEditingController _label = TextEditingController(
    text: widget.defaultLabel.split(',').first.trim(),
  );

  @override
  void dispose() {
    _label.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Save place'),
      content: AppTextField(controller: _label, label: 'Label'),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context, _label.text),
          child: const Text('Save'),
        ),
      ],
    );
  }
}

class EditProfileDialog extends StatefulWidget {
  const EditProfileDialog({required this.user, super.key});

  final AppUser? user;

  @override
  State<EditProfileDialog> createState() => _EditProfileDialogState();
}

class _EditProfileDialogState extends State<EditProfileDialog> {
  late final _name = TextEditingController(text: widget.user?.name ?? '');
  late final _phone = TextEditingController(text: widget.user?.phone ?? '');

  @override
  void dispose() {
    _name.dispose();
    _phone.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    return AlertDialog(
      title: const Text('Edit profile'),
      content: SizedBox(
        width: 380,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            AppTextField(controller: _name, label: 'Name'),
            const SizedBox(height: 10),
            AppTextField(
              controller: _phone,
              label: 'Phone',
              keyboardType: TextInputType.phone,
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: state.isLoading
              ? null
              : () async {
                  await context.read<AppState>().updateCurrentUser(
                        _name.text,
                        _phone.text,
                      );
                  if (context.mounted) Navigator.pop(context);
                },
          child: const Text('Save'),
        ),
      ],
    );
  }
}

class AddPaymentMethodDialog extends StatefulWidget {
  const AddPaymentMethodDialog({super.key});

  @override
  State<AddPaymentMethodDialog> createState() => _AddPaymentMethodDialogState();
}

class _AddPaymentMethodDialogState extends State<AddPaymentMethodDialog> {
  final _brand = TextEditingController(text: 'Visa');
  final _last4 = TextEditingController(text: '1111');
  final _label = TextEditingController(text: 'Visa ending 1111');

  @override
  void dispose() {
    _brand.dispose();
    _last4.dispose();
    _label.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    return AlertDialog(
      title: const Text('Add card'),
      content: SizedBox(
        width: 380,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            AppTextField(controller: _brand, label: 'Brand'),
            const SizedBox(height: 10),
            AppTextField(
              controller: _last4,
              label: 'Last 4 digits',
              keyboardType: TextInputType.number,
              onChanged: (value) {
                final digits = value.replaceAll(RegExp(r'\D'), '');
                _label.text =
                    '${_brand.text.trim().isEmpty ? 'Card' : _brand.text.trim()} ending ${digits.length >= 4 ? digits.substring(digits.length - 4) : digits}';
              },
            ),
            const SizedBox(height: 10),
            AppTextField(controller: _label, label: 'Label'),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: state.isLoading
              ? null
              : () async {
                  await context.read<AppState>().addPaymentMethod(
                        brand: _brand.text,
                        last4: _last4.text,
                        label: _label.text,
                      );
                  if (context.mounted) Navigator.pop(context);
                },
          child: const Text('Add card'),
        ),
      ],
    );
  }
}

class RequestRefundDialog extends StatefulWidget {
  const RequestRefundDialog({required this.ride, super.key});

  final Ride ride;

  @override
  State<RequestRefundDialog> createState() => _RequestRefundDialogState();
}

class _RequestRefundDialogState extends State<RequestRefundDialog> {
  final _reason = TextEditingController(text: 'Fare adjustment request');

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    return AlertDialog(
      title: const Text('Request refund'),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(widget.ride.destinationAddress),
            const SizedBox(height: 12),
            AppTextField(
              controller: _reason,
              label: 'Reason',
              minLines: 3,
              maxLines: 5,
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: state.isLoading
              ? null
              : () async {
                  await context.read<AppState>().requestRefund(
                        widget.ride.id,
                        _reason.text,
                      );
                  if (!context.mounted) return;
                  if (context.read<AppState>().errorMessage != null) return;
                  Navigator.pop(context);
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text(
                        'Refund request submitted. Approved refunds return within 30 days.',
                      ),
                    ),
                  );
                },
          child: const Text('Submit request'),
        ),
      ],
    );
  }
}

class SupportReplyDialog extends StatefulWidget {
  const SupportReplyDialog({required this.ticket, super.key});

  final SupportTicket ticket;

  @override
  State<SupportReplyDialog> createState() => _SupportReplyDialogState();
}

class _SupportReplyDialogState extends State<SupportReplyDialog> {
  final _message = TextEditingController(text: 'Following up on this ticket.');

  @override
  void dispose() {
    _message.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final ticket = state.supportTickets
            .where((item) => item.id == widget.ticket.id)
            .firstOrNull ??
        widget.ticket;
    return AlertDialog(
      title: Text('Ticket ${ticket.status}'),
      content: SizedBox(
        width: 440,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(ticket.message),
            const SizedBox(height: 12),
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 220),
              child: ticket.replies.isEmpty
                  ? const EmptyState('No replies yet.')
                  : ListView.separated(
                      shrinkWrap: true,
                      itemCount: ticket.replies.length,
                      separatorBuilder: (_, __) => const Divider(height: 1),
                      itemBuilder: (context, index) {
                        final reply = ticket.replies[index];
                        return ListTile(
                          dense: true,
                          contentPadding: EdgeInsets.zero,
                          leading: Icon(
                            reply.role == 'admin'
                                ? Icons.support_agent
                                : Icons.person,
                          ),
                          title: Text(reply.userName),
                          subtitle: Text(reply.message),
                        );
                      },
                    ),
            ),
            const SizedBox(height: 12),
            AppTextField(
              controller: _message,
              label: 'Reply',
              minLines: 2,
              maxLines: 4,
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Close'),
        ),
        FilledButton.icon(
          onPressed: state.isLoading
              ? null
              : () async {
                  await context.read<AppState>().replyToSupportTicket(
                        ticket.id,
                        _message.text,
                      );
                  if (!context.mounted) return;
                  _message.clear();
                },
          icon: const Icon(Icons.send),
          label: const Text('Send reply'),
        ),
      ],
    );
  }
}

class RatingDialog extends StatefulWidget {
  const RatingDialog({required this.rideId, super.key});

  final String rideId;

  @override
  State<RatingDialog> createState() => _RatingDialogState();
}

class _RatingDialogState extends State<RatingDialog> {
  int _score = 0;
  final _comment = TextEditingController();

  @override
  void dispose() {
    _comment.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Rate your ride'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          StarRatingInput(
            value: _score,
            label: 'Ride rating',
            onChanged: (value) => setState(() => _score = value),
          ),
          const SizedBox(height: 12),
          AppTextField(
            controller: _comment,
            label: 'Comment',
            minLines: 2,
            maxLines: 4,
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Close'),
        ),
        FilledButton(
          onPressed: _score == 0
              ? null
              : () {
                  context.read<AppState>().rateRide(
                        widget.rideId,
                        _score,
                        _comment.text,
                      );
                  Navigator.pop(context);
                },
          child: const Text('Submit'),
        ),
      ],
    );
  }
}
�